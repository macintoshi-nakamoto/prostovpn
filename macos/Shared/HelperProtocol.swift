import Foundation

/*
 Протокол между приложением и root-хелпером.

 Один запрос — одно соединение: приложение подключается к unix-сокету,
 пишет строку JSON, читает строку JSON и закрывает. Без состояния на
 соединении, поэтому упавшее приложение не оставляет хелпер в непонятном
 виде, а хелперу не нужно разбирать полуприсланные команды.
 */

public enum HelperPaths {
    /// Сокет в /var/run: каталог переживает перезагрузку, а его содержимое — нет,
    /// поэтому мёртвый сокет от прошлой загрузки никого не путает.
    public static let socket = "/var/run/prostovpn-helper.sock"
    public static let helperBinary = "/Library/PrivilegedHelperTools/com.prostovpn.helper"
    public static let engineBinary = "/Library/PrivilegedHelperTools/prostovpn-awg"
    public static let supportDirectory = "/Library/Application Support/ProstoVPN"
    public static let launchDaemonLabel = "com.prostovpn.helper"
    public static let launchDaemonPlist = "/Library/LaunchDaemons/com.prostovpn.helper.plist"

    /// Версия протокола. Приложение сверяет её и предлагает переустановить
    /// хелпер, если на диске остался старый: молча работать с чужим
    /// протоколом хуже, чем сказать об этом.
    public static let version = "1.0.2"
}

public enum HelperCommand: String, Codable, Sendable {
    case ping
    case up
    case down
    case status
}

public struct HelperRequest: Codable, Sendable {
    public var cmd: HelperCommand
    /// Конфигурация wg-quick целиком — как её отдаёт панель.
    public var config: String?
    /// Подменять ли системный DNS на указанный в конфиге.
    public var setDNS: Bool?
    /// Держать трафик заблокированным, если движок неожиданно умер.
    public var killSwitch: Bool?
    /// Сети, которые должны идти мимо туннеля, напрямую через физический
    /// шлюз. Список приходит от приложения, но хелпер всё равно проверяет
    /// каждую запись: он работает от root.
    public var bypass: [String]?

    public init(
        cmd: HelperCommand,
        config: String? = nil,
        setDNS: Bool? = nil,
        killSwitch: Bool? = nil,
        bypass: [String]? = nil
    ) {
        self.cmd = cmd
        self.config = config
        self.setDNS = setDNS
        self.killSwitch = killSwitch
        self.bypass = bypass
    }
}

public struct HelperStatus: Codable, Sendable {
    public var up: Bool
    public var interfaceName: String?
    /// Момент последнего рукопожатия, unix-секунды. 0 — рукопожатия не было.
    ///
    /// Поднятый интерфейс сам по себе ничего не значит: utun поднимается и
    /// когда сервер молчит, и тогда весь трафик уходит в никуда. Живым
    /// туннель делает именно рукопожатие.
    public var lastHandshake: Int
    public var rxBytes: Int64
    public var txBytes: Int64
    public var endpoint: String?
    /// Движок умер сам, не по команде «отключить».
    public var enginedDied: Bool

    public init(
        up: Bool,
        interfaceName: String? = nil,
        lastHandshake: Int = 0,
        rxBytes: Int64 = 0,
        txBytes: Int64 = 0,
        endpoint: String? = nil,
        enginedDied: Bool = false
    ) {
        self.up = up
        self.interfaceName = interfaceName
        self.lastHandshake = lastHandshake
        self.rxBytes = rxBytes
        self.txBytes = txBytes
        self.endpoint = endpoint
        self.enginedDied = enginedDied
    }
}

public struct HelperResponse: Codable, Sendable {
    public var ok: Bool
    public var error: String?
    public var version: String?
    public var status: HelperStatus?

    public init(ok: Bool, error: String? = nil, version: String? = nil, status: HelperStatus? = nil) {
        self.ok = ok
        self.error = error
        self.version = version
        self.status = status
    }
}
