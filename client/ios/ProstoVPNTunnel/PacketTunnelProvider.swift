import NetworkExtension
import os

/*
 Расширение туннеля: отдельный процесс, который и держит VPN.

 Живёт по своим правилам, и их стоит помнить, читая этот файл:

 * память жёстко ограничена (порядка 15 МБ на iOS 15+, до 50 МБ на новых).
   Превышение — мгновенное убийство процесса системой, без записи в лог.
   Поэтому здесь нет ни SwiftUI, ни тяжёлых зависимостей, а разбор конфига
   идёт построчно, а не через модель со словарями;
 * стартует без приложения — по кнопке в системных настройках, после
   перезагрузки, по Always-on. Ничего из состояния приложения тут нет:
   конфиг читается из связки ключей, доступной группе;
 * не может показать пользователю ничего. Единственный способ объяснить
   отказ — вернуть ошибку в completionHandler и записать в os_log.

 Сам туннель поднимает AmneziaWG (форк WireGuard с обфускацией): пакет
 `amneziawg-apple` подключается в целевой сборке, см. APPSTORE.md. Здесь —
 только разбор конфига панели и мост к нему.
 */

private let log = Logger(subsystem: "cc.prostovpn.tunnel", category: "PacketTunnel")

final class PacketTunnelProvider: NEPacketTunnelProvider {

    /// Разобранный конфиг: ровно то, что нужно для поднятия интерфейса.
    private struct TunnelConfig {
        var privateKey = ""
        var addresses: [String] = []
        var dns: [String] = []
        var mtu: Int = 1280
        var peerPublicKey = ""
        var endpoint = ""
        var allowedIPs: [String] = []
        var keepalive: Int = 25
        /// Параметры обфускации AmneziaWG. Пустые — обычный WireGuard.
        var obfuscation: [String: String] = [:]
    }

    override func startTunnel(options: [String: NSObject]?) async throws {
        log.info("старт туннеля")

        guard let raw = Self.storedConfig(), !raw.isEmpty else {
            // Конфига нет — приложение не успело его положить либо человек
            // вышел из учётной записи. Отдельная ошибка, чтобы в логе было
            // видно причину, а не «просто не поднялся».
            log.error("конфига нет в связке ключей")
            throw NEVPNError(.configurationInvalid)
        }

        let config = Self.parse(raw)
        guard !config.privateKey.isEmpty, !config.peerPublicKey.isEmpty, !config.endpoint.isEmpty else {
            log.error("конфиг неполный: нет ключа или адреса узла")
            throw NEVPNError(.configurationInvalid)
        }

        let settings = Self.networkSettings(for: config)
        try await setTunnelNetworkSettings(settings)

        /*
         Здесь поднимается движок AmneziaWG.

         Реализация зависит от пакета amneziawg-apple: он даёт adapter,
         которому отдаётся уже разобранный конфиг. Мост намеренно оставлен
         одной точкой — всё, что выше, от движка не зависит и не изменится
         при обновлении пакета.
         */
        try await startEngine(with: config)
        log.info("туннель поднят")
    }

    override func stopTunnel(with reason: NEProviderStopReason) async {
        log.info("остановка туннеля, причина: \(reason.rawValue, privacy: .public)")
        await stopEngine()
    }

    /// Сообщения от приложения: сейчас — только запрос статистики.
    ///
    /// Байты считает движок туннеля; приложение своей статистики не ведёт,
    /// иначе цифры на экране разошлись бы с тем, что видит панель.
    override func handleAppMessage(_ messageData: Data) async -> Data? {
        guard let text = String(data: messageData, encoding: .utf8) else { return nil }
        switch text {
        case "stats":
            let stats = await engineStatistics()
            return try? JSONSerialization.data(withJSONObject: stats)
        default:
            return nil
        }
    }

    // MARK: - Сетевые настройки

    private static func networkSettings(for config: TunnelConfig) -> NEPacketTunnelNetworkSettings {
        // Адрес узла в настройках — формальность: маршрутизацию задают
        // включённые маршруты ниже.
        let settings = NEPacketTunnelNetworkSettings(tunnelRemoteAddress: config.endpoint)

        let v4addresses = config.addresses.filter { !$0.contains(":") }
        if !v4addresses.isEmpty {
            let ipv4 = NEIPv4Settings(
                addresses: v4addresses.map { $0.components(separatedBy: "/").first ?? $0 },
                subnetMasks: v4addresses.map { _ in "255.255.255.255" }
            )
            ipv4.includedRoutes = config.allowedIPs.contains("0.0.0.0/0")
                ? [NEIPv4Route.default()]
                : config.allowedIPs.filter { !$0.contains(":") }.compactMap(Self.route4)
            settings.ipv4Settings = ipv4
        }

        /*
         IPv6 заворачиваем в туннель всегда, когда в маршрутах есть ::/0, —
         даже если у интерфейса нет собственного v6-адреса.

         Без этого система считает IPv6 доступным напрямую и предпочитает
         его: двухстековые сайты открываются мимо туннеля и видят настоящий
         адрес абонента. На Android этот же перекос давал «VPN как будто не
         работает», пока IPv4 честно шёл через туннель.
         */
        let v6addresses = config.addresses.filter { $0.contains(":") }
        if config.allowedIPs.contains("::/0") || !v6addresses.isEmpty {
            let addresses = v6addresses.isEmpty ? ["fd00::2"] : v6addresses
            let ipv6 = NEIPv6Settings(
                addresses: addresses.map { $0.components(separatedBy: "/").first ?? $0 },
                networkPrefixLengths: addresses.map { _ in 128 }
            )
            ipv6.includedRoutes = [NEIPv6Route.default()]
            settings.ipv6Settings = ipv6
        }

        if !config.dns.isEmpty {
            let dns = NEDNSSettings(servers: config.dns)
            // Пустой matchDomains означает «все домены»: иначе система
            // спрашивает резолвер оператора, и при полном туннеле имена
            // перестают разрешаться вовсе.
            dns.matchDomains = [""]
            settings.dnsSettings = dns
        }

        // MTU 1280 — гарантированный минимум IPv6, который обязан
        // пропускать любой канал. На мобильных сетях с CGNAT большие пакеты
        // тонут молча: рукопожатие проходит, «подключено» горит, а страницы
        // не открываются.
        settings.mtu = NSNumber(value: config.mtu)
        return settings
    }

    private static func route4(_ cidr: String) -> NEIPv4Route? {
        let parts = cidr.components(separatedBy: "/")
        guard parts.count == 2, let bits = Int(parts[1]), (0...32).contains(bits) else { return nil }
        let mask = bits == 0 ? 0 : (UInt32.max << (32 - bits))
        let maskText = [24, 16, 8, 0].map { String((mask >> UInt32($0)) & 0xFF) }.joined(separator: ".")
        return NEIPv4Route(destinationAddress: parts[0], subnetMask: maskText)
    }

    // MARK: - Разбор конфига

    /// Разбирает wg-quick построчно.
    ///
    /// Своими руками, а не через готовый парсер: в расширении каждый
    /// мегабайт на счету, а формат — это пары «ключ = значение» в двух
    /// секциях. Неизвестные ключи не роняют разбор: панель может добавить
    /// поле раньше, чем обновится приложение.
    static func parse(_ text: String) -> TunnelConfig {
        var config = TunnelConfig()
        var section = ""

        for rawLine in text.components(separatedBy: .newlines) {
            let line = rawLine.components(separatedBy: "#").first?.trimmingCharacters(in: .whitespaces) ?? ""
            if line.isEmpty { continue }

            if line.hasPrefix("[") && line.hasSuffix("]") {
                section = line.trimmingCharacters(in: CharacterSet(charactersIn: "[]")).lowercased()
                continue
            }

            let pair = line.components(separatedBy: "=")
            guard pair.count >= 2 else { continue }
            let key = pair[0].trimmingCharacters(in: .whitespaces).lowercased()
            // Значение может содержать «=» (base64-ключи), поэтому склеиваем
            // обратно всё, что после первого разделителя.
            let value = pair.dropFirst().joined(separator: "=").trimmingCharacters(in: .whitespaces)
            let list = { value.components(separatedBy: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty } }

            switch (section, key) {
            case ("interface", "privatekey"): config.privateKey = value
            case ("interface", "address"): config.addresses = list()
            case ("interface", "dns"): config.dns = list()
            case ("interface", "mtu"): config.mtu = Int(value) ?? config.mtu
            case ("peer", "publickey"): config.peerPublicKey = value
            case ("peer", "endpoint"): config.endpoint = value
            case ("peer", "allowedips"): config.allowedIPs = list()
            case ("peer", "persistentkeepalive"): config.keepalive = Int(value) ?? config.keepalive
            // Обфускация AmneziaWG: Jc, Jmin, Jmax, S1, S2, H1..H4.
            case ("interface", "jc"), ("interface", "jmin"), ("interface", "jmax"),
                 ("interface", "s1"), ("interface", "s2"),
                 ("interface", "h1"), ("interface", "h2"), ("interface", "h3"), ("interface", "h4"):
                config.obfuscation[key] = value
            default:
                continue
            }
        }
        return config
    }

    /// Конфиг из связки ключей — общей для приложения и расширения.
    ///
    /// Дублирует запрос из Keychain намеренно: тащить в расширение файл
    /// приложения значит тащить и его зависимости, а памяти здесь мало.
    private static func storedConfig() -> String? {
        let group = Bundle.main.object(forInfoDictionaryKey: "KeychainAccessGroup") as? String
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "cc.prostovpn.app",
            kSecAttrAccount as String: "prosto.tunnelConfig",
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        if let group { query[kSecAttrAccessGroup as String] = group }

        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    // MARK: - Мост к движку

    /*
     Точка подключения amneziawg-apple.

     Оставлено тремя методами, чтобы движок менялся в одном месте. Сборка
     без пакета компилируется и честно отказывается поднимать туннель — это
     лучше, чем не собираться вовсе: экраны и вход при этом отлаживаются.
     */

    private func startEngine(with config: TunnelConfig) async throws {
        #if canImport(AmneziaWG)
        try await AmneziaBridge.shared.start(config: config, packetFlow: packetFlow)
        #else
        log.error("пакет amneziawg-apple не подключён — туннель не поднимется")
        throw NEVPNError(.configurationInvalid)
        #endif
    }

    private func stopEngine() async {
        #if canImport(AmneziaWG)
        await AmneziaBridge.shared.stop()
        #endif
    }

    private func engineStatistics() async -> [String: Any] {
        #if canImport(AmneziaWG)
        return await AmneziaBridge.shared.statistics()
        #else
        return ["rx": 0, "tx": 0]
        #endif
    }
}
