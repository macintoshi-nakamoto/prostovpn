import Foundation

/// Жизненный цикл туннеля: движок, интерфейс, маршруты, DNS.
///
/// Единственный владелец состояния в хелпере. Все изменения проходят через
/// `lock`, поэтому одновременные «подключить» и «отключить» не оставят
/// половину настроек применённой.
final class Tunnel {

    private let lock = NSLock()

    private var engine: Process?
    private var interfaceName: String?
    /// Всё, что мы увели мимо туннеля: сервер VPN и сети обхода. Эти
    /// маршруты не исчезают вместе с интерфейсом, их надо снимать руками.
    private var directRoutes: [String] = []
    /// Сети раздельного туннелирования. Отдельно от `directRoutes`, потому
    /// что снимаются тем же пакетным способом, каким ставились.
    private var bulkBypass: [String] = []
    private var bulkExit: SystemNetwork.DefaultRoute?
    private var killSwitchArmed = false
    private var engineDied = false
    private var blackholeInstalled = false

    // MARK: - Публичный интерфейс

    func up(configText: String, setDNS: Bool, killSwitch: Bool, bypass: [String]) throws -> String {
        lock.lock()
        defer { lock.unlock() }

        // Повторное подключение поверх старого — обычное дело при смене сервера.
        teardownLocked()

        let config = try WGQuick.parse(configText)

        // Эндпоинты разрешаем до поднятия интерфейса: после того как маршрут
        // по умолчанию уедет в туннель, DNS уже может не ответить.
        var resolved: [String: String] = [:]
        var endpointIPs: [String] = []
        for peer in config.peers {
            guard let endpoint = peer.endpoint else { continue }
            guard let address = SystemNetwork.resolveEndpoint(endpoint) else {
                throw HelperError("не удалось определить адрес сервера: \(endpoint)")
            }
            resolved[endpoint] = address
            if let (host, _) = WGQuick.splitEndpoint(address) {
                endpointIPs.append(host.trimmingCharacters(in: CharacterSet(charactersIn: "[]")))
            }
        }

        // Оставшийся от прошлой сессии блэкхол снимаем: иначе новый туннель
        // поднимется в тишине — рукопожатию некуда будет уйти.
        if blackholeInstalled {
            SystemNetwork.removeBlackhole()
            blackholeInstalled = false
        }

        // Снимок выхода в интернет до того, как маршрут по умолчанию уедет
        // в туннель. Спросить позже — получить в ответ свой же utun и
        // закольцевать всё, что мы собирались пустить напрямую.
        let exitV4 = SystemNetwork.currentDefaultRoute()
        let exitV6 = SystemNetwork.currentDefaultRoute(ipv6: true)

        let name: String
        do {
            name = try startEngine()
        } catch {
            // Движок мог успеть создать интерфейс до отказа — убираем за собой,
            // иначе следующая попытка начнётся с мусора от предыдущей.
            teardownLocked()
            throw error
        }
        interfaceName = name
        killSwitchArmed = killSwitch
        engineDied = false

        do {
            let payload = WGQuick.uapiPayload(config, resolvedEndpoints: resolved)
            let response = try UAPI.exchange(interfaceName: name, request: payload)
            // Движок отвечает errno=0 при успехе. Ненулевой код значит, что
            // часть настроек не применилась — поднимать такой туннель нельзя.
            if let errno = errnoValue(in: response), errno != 0 {
                throw HelperError("движок отклонил конфигурацию (errno=\(errno))")
            }

            for ip in endpointIPs {
                addDirect(ip, v4: exitV4, v6: exitV6)
            }

            try SystemNetwork.configureInterface(name, addresses: config.addresses, mtu: config.mtu)

            let allowed = config.peers.flatMap(\.allowedIPs)
            SystemNetwork.addRoutes(allowed, interfaceName: name)

            // Обход ставим после маршрутов туннеля: сеть /24 точнее, чем
            // половинки 0.0.0.0/1, поэтому выигрывает она — независимо от
            // порядка, но так очевиднее, что чему предшествует.
            applyBypassLocked(bypass, v4: exitV4, v6: exitV6)

            if setDNS {
                SystemNetwork.applyDNS(config.dns)
            }
        } catch {
            teardownLocked()
            throw error
        }

        return name
    }

    func down() {
        lock.lock()
        defer { lock.unlock() }
        killSwitchArmed = false
        teardownLocked()
        if blackholeInstalled {
            SystemNetwork.removeBlackhole()
            blackholeInstalled = false
        }
    }

    func status() -> HelperStatus {
        lock.lock()
        let name = interfaceName
        let alive = engine?.isRunning ?? false
        let died = engineDied
        lock.unlock()

        guard let name, alive else {
            return HelperStatus(up: false, enginedDied: died)
        }
        guard let snapshot = UAPI.snapshot(interfaceName: name) else {
            return HelperStatus(up: true, interfaceName: name, enginedDied: died)
        }
        return HelperStatus(
            up: true,
            interfaceName: name,
            lastHandshake: snapshot.lastHandshake,
            rxBytes: snapshot.rxBytes,
            txBytes: snapshot.txBytes,
            endpoint: snapshot.endpoint,
            enginedDied: died
        )
    }

    // MARK: - Движок

    private func startEngine() throws -> String {
        let fileManager = FileManager.default
        try? fileManager.createDirectory(
            atPath: UAPI.socketDirectory,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )

        let nameFile = "\(UAPI.socketDirectory)/prosto.name"
        try? fileManager.removeItem(atPath: nameFile)

        guard fileManager.isExecutableFile(atPath: HelperPaths.engineBinary) else {
            throw HelperError("движок не найден: \(HelperPaths.engineBinary)")
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: HelperPaths.engineBinary)
        // Держим движок своим ребёнком (-f): иначе он уходит в демоны, и
        // проследить, жив ли туннель, можно будет только по косвенным признакам.
        process.arguments = ["-f", "utun"]
        process.environment = [
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
            "WG_TUN_NAME_FILE": nameFile,
            "WG_PROCESS_FOREGROUND": "1",
            "LOG_LEVEL": "error",
        ]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice

        process.terminationHandler = { [weak self] _ in
            self?.engineTerminated()
        }

        do {
            try process.run()
        } catch {
            throw HelperError("не удалось запустить движок: \(error.localizedDescription)")
        }
        engine = process

        // Имя интерфейса выбирает ядро, движок записывает его в файл.
        guard let name = waitForName(at: nameFile, process: process) else {
            stopEngineLocked()
            throw HelperError("движок не создал сетевой интерфейс")
        }

        guard waitForSocket(UAPI.socketPath(for: name), process: process) else {
            stopEngineLocked()
            throw HelperError("движок не открыл управляющий сокет")
        }

        return name
    }

    private func waitForName(at path: String, process: Process) -> String? {
        let deadline = Date().addingTimeInterval(8)
        while Date() < deadline {
            if !process.isRunning { return nil }
            if let text = try? String(contentsOfFile: path, encoding: .utf8) {
                let name = text.trimmingCharacters(in: .whitespacesAndNewlines)
                if !name.isEmpty { return name }
            }
            usleep(50_000)
        }
        return nil
    }

    private func waitForSocket(_ path: String, process: Process) -> Bool {
        let deadline = Date().addingTimeInterval(8)
        while Date() < deadline {
            if !process.isRunning { return false }
            if FileManager.default.fileExists(atPath: path) { return true }
            usleep(50_000)
        }
        return false
    }

    private func engineTerminated() {
        lock.lock()
        defer { lock.unlock() }
        // Плановое отключение обнуляет engine до завершения процесса,
        // поэтому сюда попадает только неожиданная смерть.
        guard engine != nil else { return }
        engineDied = true
        engine = nil
        interfaceName = nil
        if killSwitchArmed && !blackholeInstalled {
            SystemNetwork.installBlackhole(ipv6: true)
            blackholeInstalled = true
        } else {
            releaseSystemChangesLocked()
        }
    }

    // MARK: - Уборка

    /// Снимает всё, что мы навесили на систему. Вызывается под `lock`.
    private func teardownLocked() {
        stopEngineLocked()
        interfaceName = nil
        engineDied = false
        releaseSystemChangesLocked()
    }

    /// Останавливает движок по нашей воле.
    ///
    /// Обработчик завершения снимается первым: он рассчитан на неожиданную
    /// смерть движка и под уже взятым `lock` встал бы намертво.
    private func stopEngineLocked() {
        guard let process = engine else { return }
        engine = nil
        process.terminationHandler = nil
        process.terminate()
        let deadline = Date().addingTimeInterval(3)
        while process.isRunning && Date() < deadline {
            usleep(20_000)
        }
        if process.isRunning {
            kill(process.processIdentifier, SIGKILL)
        }
    }

    private func releaseSystemChangesLocked() {
        // Маршруты через utun исчезают вместе с интерфейсом, а вот всё, что
        // мы увели в обход, и подменённый DNS надо снять руками.
        if !bulkBypass.isEmpty {
            if let exit = bulkExit, let socket = RouteSocket(), let target = routeExit(for: exit) {
                socket.apply(.remove, networks: bulkBypass, via: target)
            }
            bulkBypass.removeAll()
            bulkExit = nil
        }
        for destination in directRoutes {
            SystemNetwork.removeDirectRoute(destination)
        }
        directRoutes.removeAll()
        SystemNetwork.restoreDNS()
    }

    /// Прописывает список обхода одним заходом через маршрутный сокет.
    ///
    /// В списке раздельного туннелирования тысячи сетей: по одному вызову
    /// `/sbin/route` подключение растянулось бы на десяток секунд, и человек
    /// решил бы, что приложение зависло.
    private func applyBypassLocked(
        _ networks: [String],
        v4: SystemNetwork.DefaultRoute?,
        v6: SystemNetwork.DefaultRoute?
    ) {
        let valid = networks.filter { SplitTunnelList.isNetwork($0) }
        guard !valid.isEmpty else { return }

        let ipv4 = valid.filter { !$0.contains(":") }
        let ipv6 = valid.filter { $0.contains(":") }

        if let v4, !ipv4.isEmpty, let socket = RouteSocket(), let exit = routeExit(for: v4) {
            let outcome = socket.apply(.add, networks: ipv4, via: exit)
            bulkBypass.append(contentsOf: ipv4)
            // Выход запоминаем вместе со списком: снимать маршруты придётся
            // тем же путём, а к тому времени маршрут по умолчанию уже наш.
            bulkExit = v4
            if let error = outcome.firstError, outcome.applied == 0 {
                FileHandle.standardError.write(
                    Data("обход не применился: \(error)\n".utf8)
                )
            }
        }

        // IPv6 в списках встречается единицами — там хватает обычного route.
        for cidr in ipv6 {
            addDirect(cidr, v4: v4, v6: v6)
        }
    }

    private func routeExit(for route: SystemNetwork.DefaultRoute) -> RouteSocket.Exit? {
        if let gateway = route.gateway, !gateway.hasPrefix("link#") {
            var address = in_addr()
            if inet_pton(AF_INET, gateway, &address) == 1 {
                return .gateway(address)
            }
        }
        let index = if_nametoindex(route.interfaceName)
        return index > 0 ? .interfaceIndex(UInt16(index)) : nil
    }

    /// Уводит адрес или сеть мимо туннеля и запоминает, чтобы убрать потом.
    private func addDirect(
        _ destination: String,
        v4: SystemNetwork.DefaultRoute?,
        v6: SystemNetwork.DefaultRoute?
    ) {
        let exit = destination.contains(":") ? v6 : v4
        guard let exit else { return }
        SystemNetwork.addDirectRoute(destination, via: exit)
        directRoutes.append(destination)
    }

    private func errnoValue(in response: String) -> Int? {
        for line in response.components(separatedBy: .newlines) where line.hasPrefix("errno=") {
            return Int(line.dropFirst("errno=".count))
        }
        return nil
    }
}

struct HelperError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}
