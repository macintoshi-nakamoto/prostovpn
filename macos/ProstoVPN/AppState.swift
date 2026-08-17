import SwiftUI
import Combine

/// Состояние приложения: аккаунт, подписка, серверы, туннель.
///
/// Здесь же единственное место, которое разговаривает с хелпером, — чтобы
/// «подключено» на экране всегда означало живой туннель, а не нажатую кнопку.
@MainActor
final class AppState: ObservableObject {

    enum Phase: Equatable {
        case off
        case connecting
        case on
        case disconnecting
    }

    /// Состояние в приложении одно. Туннель тоже один, и второй набор
    /// подписок на него показывал бы на экране не то, что происходит.
    static let shared = AppState()

    // MARK: - Публикуемое

    @Published private(set) var phase: Phase = .off
    @Published private(set) var seconds: Int = 0
    @Published private(set) var servers: [PanelServer] = []
    @Published private(set) var subscription: PanelSubscription?
    @Published private(set) var account: PanelAccount?
    @Published private(set) var helperReady = false

    /// Почему список стран пуст. Текст пишет панель — здесь его только
    /// показывают: пустой экран без объяснения человек читает как поломку.
    @Published private(set) var notice: String = ""

    /// Почему человека выкинуло на экран входа. Живёт только в памяти:
    /// signOut() чистит хранилища, а причина обязана его пережить.
    @Published private(set) var signedOutReason: String = ""

    @Published var errorMessage: String?
    @Published var isBusy = false

    @Published var lang: String {
        didSet { defaults.set(lang, forKey: Keys.lang) }
    }

    @Published var selectedServerID: Int? {
        didSet { defaults.set(selectedServerID ?? -1, forKey: Keys.selectedServer) }
    }

    /// Обновление приложения.
    ///
    /// Живёт здесь, а не на экране настроек: проверка стартует вместе с
    /// приложением, а баннер обязательного обновления рисуется на главном
    /// экране до всякого захода в настройки.
    let updates: UpdateManager

    var t: L10n { L10n.of(lang) }

    var isLoggedIn: Bool { account != nil || !servers.isEmpty }

    var currentServer: PanelServer? {
        servers.first { $0.id == selectedServerID } ?? servers.first
    }

    /// Экран входа забирает причину: показывается она ровно один раз.
    func consumeSignedOutReason() -> String {
        let reason = signedOutReason
        signedOutReason = ""
        return reason
    }

    // MARK: - Настройки, влияющие на туннель

    var useVPNDNS: Bool {
        get { defaults.object(forKey: Keys.dns) as? Bool ?? true }
        set { defaults.set(newValue, forKey: Keys.dns) }
    }

    var killSwitch: Bool {
        get { defaults.bool(forKey: Keys.killSwitch) }
        set { defaults.set(newValue, forKey: Keys.killSwitch) }
    }

    /// Раздельное туннелирование: сети из активного списка идут мимо VPN.
    ///
    /// Включено по умолчанию: с зарубежного адреса вход в ЕСИА не проходит,
    /// банки требуют подтверждений, а школьные порталы не открываются вовсе.
    /// Человек, поставивший VPN, не должен из-за него потерять Госуслуги.
    var splitTunnel: Bool {
        get { defaults.object(forKey: Keys.bypass) as? Bool ?? true }
        set { defaults.set(newValue, forKey: Keys.bypass) }
    }

    /// Подключаться сразу после запуска.
    var autoConnect: Bool {
        get { defaults.bool(forKey: Keys.autoConnect) }
        set { defaults.set(newValue, forKey: Keys.autoConnect) }
    }

    let tunnelFiles = TunnelFiles()

    /// Адрес панели зашит в сборку. В настройках его нет намеренно: поле,
    /// которым пользуются раз в жизни, только путает, а ошибка в нём выглядит
    /// как «приложение не работает».
    ///
    /// Читать его из UserDefaults тоже перестали: ранние сборки записывали
    /// туда адрес, которого больше нет, и сохранённое значение перекрывало
    /// правильный — приложение молча стучалось в никуда.
    static let defaultPanelAddress = "https://prostovpn.cc"

    // MARK: - Внутреннее

    private let defaults = UserDefaults.standard
    private let panel: PanelClient
    private var token: String? {
        didSet { Keychain.set(token, for: Keys.token) }
    }

    private var timer: Timer?
    private var connectedAt: Date?
    private var watchdog: Task<Void, Never>?
    private var heartbeat: Task<Void, Never>?
    private var accountWatch: Task<Void, Never>?
    private var autoConnectTried = false
    private var cancellables = Set<AnyCancellable>()

    /// Как часто перечитывать подписку, пока приложение открыто.
    ///
    /// Тот же ритм, что у Android и Windows: этим опросом приложение узнаёт,
    /// что устройство отвязали, кончился трафик или продлилась подписка.
    private let accountPollSeconds: UInt64 = 60

    private enum Keys {
        static let lang = "prosto.lang"
        static let selectedServer = "prosto.selectedServer"
        static let dns = "prosto.dns"
        static let killSwitch = "prosto.killSwitch"
        static let bypass = "prosto.bypassRussianServices"
        static let autoConnect = "prosto.autoconnect"
        static let panel = "prosto.panel"
        static let token = "panel.token"
        static let servers = "panel.servers"
        static let account = "prosto.account"
        static let subscription = "prosto.subscription"
    }

    init() {
        // Стартовый язык — из системной локали, а не всегда русский:
        // приложение ставят и не только с русской системой.
        let systemLanguage = Locale.preferredLanguages.first?.hasPrefix("ru") == true ? "ru" : "en"
        lang = defaults.string(forKey: Keys.lang) ?? systemLanguage

        let saved = defaults.integer(forKey: Keys.selectedServer)
        selectedServerID = saved == 0 || saved == -1 ? nil : saved

        // Адрес прежних сборок остался в настройках — он больше не отвечает.
        defaults.removeObject(forKey: Keys.panel)
        let client = PanelClient(baseURL: URL(string: Self.defaultPanelAddress)!)
        panel = client
        updates = UpdateManager(panel: client)

        token = Keychain.get(Keys.token)
        account = loadCachedAccount()
        subscription = loadCachedSubscription()
        servers = loadCachedServers()
        if selectedServerID == nil { selectedServerID = servers.first?.id }

        // Ход обновления виден на главном экране и в настройках, а подписаны
        // они на AppState: без ретрансляции карточка обновления замирала бы
        // на «Проверяем…» до следующего изменения чего-то ещё.
        updates.objectWillChange
            .sink { [weak self] in self?.objectWillChange.send() }
            .store(in: &cancellables)

        refreshHelperState()
        syncPhaseWithHelper()
        startAccountWatch()
        // Версию спрашиваем сразу, не дожидаясь захода в настройки:
        // обязательное обновление должно встретить человека баннером на
        // главном — и дойти даже до того, кто ещё не вошёл.
        updates.check()
    }

    // MARK: - Служба

    func refreshHelperState() {
        Task.detached(priority: .userInitiated) {
            let ready = HelperClient.isReady()
            await MainActor.run { self.helperReady = ready }
        }
    }

    func installHelper() {
        isBusy = true
        Task.detached(priority: .userInitiated) {
            do {
                try HelperInstaller.install()
                await MainActor.run {
                    self.helperReady = true
                    self.isBusy = false
                }
            } catch is HelperInstaller.Cancelled {
                await MainActor.run { self.isBusy = false }
            } catch {
                await MainActor.run {
                    self.errorMessage = error.localizedDescription
                    self.isBusy = false
                }
            }
        }
    }

    /// Приложение могли перезапустить при поднятом туннеле — состояние
    /// берём у хелпера, а не считаем, что всё выключено.
    private func syncPhaseWithHelper() {
        Task.detached(priority: .utility) {
            guard let response = try? HelperClient.send(HelperRequest(cmd: .status), timeout: 3),
                  let status = response.status, status.up
            else { return }
            await MainActor.run {
                self.phase = .on
                self.startTimer(from: Date())
                self.startWatchdog()
                self.startHeartbeat()
            }
        }
    }

    // MARK: - Вход

    func login(login: String, password: String) async {
        errorMessage = nil
        isBusy = true
        defer { isBusy = false }

        do {
            let result = try await panel.login(
                login: login,
                password: password,
                deviceID: DeviceIdentity.installID,
                deviceName: DeviceIdentity.name
            )
            token = result.token
            apply(account: result.account)
            apply(subscription: result.subscription, notice: result.notice)
            apply(servers: result.servers)
            signedOutReason = ""
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Вход по ключу `vpn://` — без панели и подписки, сервер один.
    func applyAccessKey(_ raw: String) -> Bool {
        guard let key = AccessKeyParser.parse(raw),
              (try? WGQuick.parse(key.config)) != nil
        else {
            errorMessage = t.errBadKey
            return false
        }

        let host = key.host ?? AccessKeyParser.endpointHost(in: key.config) ?? "—"
        let server = PanelServer(
            id: Self.accessKeyServerID,
            name: host,
            config: key.config,
            host: host
        )
        notice = ""
        apply(servers: [server])
        errorMessage = nil
        signedOutReason = ""
        refreshGeo(for: server)
        return true
    }

    static let accessKeyServerID = -1

    /// Перечитывает страны и подписку: их могли продлить или закрыть.
    func refreshServers() async {
        guard let token else { return }
        do {
            let result = try await panel.servers(token: token)
            // Страны были, а теперь их нет — доступ закрыли, пока приложение
            // работало: кончился трафик, срок или устройство отвязали.
            let lostAccess = result.servers.isEmpty && !servers.isEmpty
            apply(subscription: result.subscription, notice: result.notice)
            apply(servers: result.servers)
            if lostAccess, phase == .on || phase == .connecting {
                await disconnect()
                errorMessage = result.notice?.nilIfEmpty ?? t.subscriptionOver
            }
        } catch let error as PanelError where error.revokesSession {
            // Гасим сессию ТОЛЬКО когда панель прямо сказала, что токен не
            // годится. Пятисотка, перезапуск панели или моргнувшая сеть —
            // это временно, а стирание сессии необратимо.
            await signOut(reason: t.noticeRemoteSignout)
            Notifier.shared.notify(
                .signedOut,
                title: t.notifSignedOutTitle,
                body: t.noticeRemoteSignout
            )
        } catch {
            // Молча: список стран у нас уже есть, а всплывающая ошибка на
            // каждый неудачный опрос раз в минуту — это шум, а не помощь.
        }
    }

    /// Периодический опрос панели, пока приложение живо.
    private func startAccountWatch() {
        accountWatch?.cancel()
        let period = accountPollSeconds
        accountWatch = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: period * 1_000_000_000)
                guard let self else { return }
                // refreshServers сам ничего не делает без токена: по ключу
                // доступа спрашивать панель не о чем.
                await self.refreshServers()
            }
        }
    }

    func signOut(reason: String = "") async {
        await disconnect()
        if let token {
            await panel.logout(token: token)
        }
        token = nil
        account = nil
        subscription = nil
        servers = []
        selectedServerID = nil
        notice = ""
        errorMessage = nil
        autoConnectTried = true
        defaults.removeObject(forKey: Keys.account)
        defaults.removeObject(forKey: Keys.subscription)
        Keychain.remove(Keys.servers)
        // Именно после очистки: причина живёт в памяти и должна дожить до
        // экрана входа.
        signedOutReason = reason
    }

    private func apply(account value: PanelAccount) {
        account = value
        if let data = try? JSONEncoder().encode(value) {
            defaults.set(data, forKey: Keys.account)
        }
    }

    /// Переносит подписку из ответа панели в состояние и настройки.
    ///
    /// Одним местом на оба вызова — вход и обновление списка стран. Пока их
    /// было два, любое новое поле требовалось не забыть дважды.
    private func apply(subscription value: PanelSubscription, notice text: String?) {
        subscription = value
        // notice не сохраняем: это объяснение конкретного ответа панели,
        // протухшее показывать хуже, чем никакое.
        notice = text?.nilIfEmpty ?? ""
        if let data = try? JSONEncoder().encode(value) {
            defaults.set(data, forKey: Keys.subscription)
        }
        announce(value)
    }

    /// Системные сообщения о подписке.
    ///
    /// Не чаще раза в двенадцать часов: опрос идёт каждую минуту, и без
    /// ограничения «трафик заканчивается» приходило бы шестьдесят раз в час.
    private func announce(_ value: PanelSubscription) {
        if value.traffic_low, let left = value.traffic_left_bytes {
            Notifier.shared.notify(
                .trafficLow,
                title: t.notifTrafficTitle,
                body: t.trafficLow(t.bytes(left)),
                throttle: 12 * 3600
            )
        }
        if value.expires_soon, value.active, let days = value.days_left {
            Notifier.shared.notify(
                .expiresSoon,
                title: t.notifExpiresTitle,
                body: t.expiresSoon(t.days(days)),
                throttle: 12 * 3600
            )
        }
    }

    private func apply(servers list: [PanelServer]) {
        servers = list
        if let id = selectedServerID, list.contains(where: { $0.id == id }) {
            // выбранный сервер на месте — не трогаем
        } else {
            selectedServerID = list.first?.id
        }
        cache(servers: list)
    }

    // MARK: - Туннель

    /// Переключает раздельное туннелирование и сразу применяет его.
    ///
    /// Маршруты ставятся при поднятии туннеля, поэтому на живом соединении
    /// настройка вступает в силу только переподключением. Молча отложить её
    /// до следующего раза — значит соврать переключателем.
    func setSplitTunnel(_ enabled: Bool) {
        guard enabled != splitTunnel else { return }
        splitTunnel = enabled
        reapplyRoutes()
    }

    func selectTunnelFile(_ file: TunnelFile) {
        guard tunnelFiles.activeID != file.id else { return }
        tunnelFiles.activeID = file.id
        if splitTunnel { reapplyRoutes() }
    }

    func addTunnelFile(from url: URL) throws {
        try tunnelFiles.add(from: url)
        if splitTunnel { reapplyRoutes() }
    }

    func removeTunnelFile(_ file: TunnelFile) {
        let wasActive = tunnelFiles.activeID == file.id
        tunnelFiles.remove(file)
        if splitTunnel && wasActive { reapplyRoutes() }
    }

    /// Список маршрутов живёт только внутри поднятого туннеля, поэтому
    /// применить изменения можно единственным способом — переподключиться.
    private func reapplyRoutes() {
        guard phase == .on else { return }
        Task {
            await disconnect()
            await connect()
        }
    }

    func toggle() {
        switch phase {
        case .off:
            Task { await connect() }
        case .on, .connecting:
            Task { await disconnect() }
        case .disconnecting:
            break
        }
    }

    /// Подключение при запуске, если человек его включил. Один раз за сеанс.
    func maybeAutoConnect() async {
        guard !autoConnectTried else { return }
        autoConnectTried = true
        guard autoConnect, phase == .off, currentServer != nil else { return }
        await connect()
    }

    func connect() async {
        guard phase == .off else { return }
        guard let server = currentServer else {
            errorMessage = notice.nilIfEmpty ?? t.noServersHint
            return
        }

        errorMessage = nil
        Notifier.shared.clear(.dropped)
        // Разрешение спрашиваем здесь: к первому подключению уже понятно, о
        // чём вообще будут сообщения.
        Notifier.shared.requestPermissionIfNeeded()

        if !helperReady {
            isBusy = true
            let installed: Result<Void, Error> = await Task.detached {
                do { try HelperInstaller.ensureInstalled(); return .success(()) }
                catch { return .failure(error) }
            }.value
            isBusy = false
            switch installed {
            case .success:
                helperReady = true
            case .failure(let error):
                if !(error is HelperInstaller.Cancelled) {
                    errorMessage = error.localizedDescription
                }
                return
            }
        }

        phase = .connecting

        let config = server.config
        let dns = useVPNDNS
        let kill = killSwitch
        let bypass = splitTunnel ? tunnelFiles.activeNetworks() : []

        let outcome: Result<Void, Error> = await Task.detached(priority: .userInitiated) {
            do {
                let response = try HelperClient.send(
                    HelperRequest(cmd: .up, config: config, setDNS: dns, killSwitch: kill, bypass: bypass),
                    timeout: 40
                )
                guard response.ok else {
                    throw HelperClient.Unavailable(reason: response.error ?? "не удалось поднять туннель")
                }
                return .success(())
            } catch {
                return .failure(error)
            }
        }.value

        if case .failure(let error) = outcome {
            phase = .off
            errorMessage = (error as? HelperClient.Unavailable) != nil
                ? error.localizedDescription
                : t.errTunnelFailed
            return
        }

        // Поднятый интерфейс — ещё не связь. Ждём рукопожатия: без него весь
        // трафик уходит в туннель, который никуда не ведёт.
        let handshake = await waitForHandshake(seconds: 20)
        guard phase == .connecting else { return }

        if handshake {
            phase = .on
            startTimer(from: Date())
            startWatchdog()
            startHeartbeat()
            Notifier.shared.notify(
                .connected,
                title: t.notifConnectedTitle,
                body: connectionSummary(server)
            )
        } else {
            await sendDown()
            phase = .off
            errorMessage = t.errNoHandshake
        }
    }

    /// «Нидерланды · Амстердам» — то, что человек выбирал на экране.
    private func connectionSummary(_ server: PanelServer) -> String {
        let name = server.name(lang: lang)
        if let city = server.city(lang: lang), !city.isEmpty, city != name {
            return "\(name) · \(city)"
        }
        return name
    }

    func disconnect() async {
        guard phase != .off, phase != .disconnecting else { return }
        phase = .disconnecting
        stopTimer()
        watchdog?.cancel(); watchdog = nil
        heartbeat?.cancel(); heartbeat = nil
        await sendDown()
        phase = .off
    }

    private func sendDown() async {
        _ = await Task.detached(priority: .userInitiated) {
            try? HelperClient.send(HelperRequest(cmd: .down), timeout: 15)
        }.value
    }

    private func waitForHandshake(seconds limit: Int) async -> Bool {
        let deadline = Date().addingTimeInterval(TimeInterval(limit))
        while Date() < deadline {
            if Task.isCancelled { return false }
            let status = await Task.detached(priority: .utility) {
                try? HelperClient.send(HelperRequest(cmd: .status), timeout: 5).status
            }.value
            if let status {
                if !status.up { return false }
                if status.lastHandshake > 0 { return true }
            }
            try? await Task.sleep(nanoseconds: 500_000_000)
        }
        return false
    }

    /// Пока туннель поднят, следим, что он жив: упавший движок иначе выглядел
    /// бы как рабочее соединение без интернета.
    private func startWatchdog() {
        watchdog?.cancel()
        watchdog = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 3_000_000_000)
                guard let self else { return }
                let status = await Task.detached(priority: .utility) {
                    try? HelperClient.send(HelperRequest(cmd: .status), timeout: 5).status
                }.value
                guard self.phase == .on else { return }
                guard let status else { continue }
                if !status.up {
                    self.stopTimer()
                    self.phase = .off
                    self.errorMessage = self.t.errTunnelDropped
                    self.heartbeat?.cancel()
                    self.heartbeat = nil
                    // Окно может быть закрыто: единственный способ сказать
                    // человеку, что трафик снова идёт мимо VPN.
                    Notifier.shared.notify(
                        .dropped,
                        title: self.t.notifDroppedTitle,
                        body: self.t.notifDroppedBody
                    )
                    return
                }
            }
        }
    }

    /// Отметка в панели, пока подключены: из неё видно, кто сейчас онлайн.
    private func startHeartbeat() {
        heartbeat?.cancel()
        guard let token else { return }
        heartbeat = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                _ = try? await self.panel.heartbeat(token: token)
                try? await Task.sleep(nanoseconds: 60_000_000_000)
            }
        }
    }

    // MARK: - Таймер

    private func startTimer(from date: Date) {
        connectedAt = date
        seconds = 0
        let timer = Timer(timeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, let anchor = self.connectedAt else { return }
                let elapsed = Int(Date().timeIntervalSince(anchor))
                if elapsed != self.seconds { self.seconds = elapsed }
            }
        }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    private func stopTimer() {
        timer?.invalidate()
        timer = nil
        connectedAt = nil
        seconds = 0
    }

    var formattedDuration: String {
        let h = seconds / 3600, m = (seconds % 3600) / 60, s = seconds % 60
        return h > 0
            ? String(format: "%d:%02d:%02d", h, m, s)
            : String(format: "%02d:%02d", m, s)
    }

    // MARK: - Кэш

    /// Конфиги — это доступ к VPN, поэтому лежат в связке ключей, а не в
    /// UserDefaults, откуда их прочитал бы любой процесс пользователя.
    private func cache(servers list: [PanelServer]) {
        guard let data = try? JSONEncoder().encode(list) else { return }
        Keychain.set(String(data: data, encoding: .utf8), for: Keys.servers)
    }

    private func loadCachedServers() -> [PanelServer] {
        guard let text = Keychain.get(Keys.servers), let data = text.data(using: .utf8) else { return [] }
        return (try? JSONDecoder().decode([PanelServer].self, from: data)) ?? []
    }

    private func loadCachedAccount() -> PanelAccount? {
        guard let data = defaults.data(forKey: Keys.account) else {
            // Прежние сборки клали сюда один логин строкой.
            guard let login = defaults.string(forKey: Keys.account) else { return nil }
            return PanelAccount(login: login)
        }
        return try? JSONDecoder().decode(PanelAccount.self, from: data)
    }

    private func loadCachedSubscription() -> PanelSubscription? {
        guard let data = defaults.data(forKey: Keys.subscription) else { return nil }
        return try? JSONDecoder().decode(PanelSubscription.self, from: data)
    }

    // MARK: - Геолокация сервера по ключу

    /// У ключа нет ни страны, ни города — спрашиваем их по адресу сервера,
    /// иначе в списке будет голый IP.
    private func refreshGeo(for server: PanelServer) {
        guard server.id == Self.accessKeyServerID, !server.host.isEmpty else { return }
        let host = server.host
        let language = lang
        Task { [weak self] in
            guard let url = URL(
                string: "http://ip-api.com/json/\(host)?fields=status,country,countryCode,city&lang=\(language)"
            ) else { return }
            guard let (data, _) = try? await URLSession.shared.data(from: url),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  json["status"] as? String == "success"
            else { return }

            await MainActor.run {
                guard let self, var updated = self.servers.first(where: { $0.id == Self.accessKeyServerID }),
                      updated.host == host
                else { return }
                updated.country = json["country"] as? String
                updated.country_en = json["country"] as? String
                updated.city = json["city"] as? String
                updated.city_en = json["city"] as? String
                updated.country_code = json["countryCode"] as? String
                self.servers = self.servers.map { $0.id == Self.accessKeyServerID ? updated : $0 }
                self.cache(servers: self.servers)
            }
        }
    }
}
