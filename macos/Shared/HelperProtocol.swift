import Foundation

public enum HelperPaths {
    public static let socket = "/var/run/prostovpn-helper.sock"
    public static let helperBinary = "/Library/PrivilegedHelperTools/com.prostovpn.helper"
    public static let engineBinary = "/Library/PrivilegedHelperTools/prostovpn-awg"
    public static let supportDirectory = "/Library/Application Support/ProstoVPN"
    public static let launchDaemonLabel = "com.prostovpn.helper"
    public static let launchDaemonPlist = "/Library/LaunchDaemons/com.prostovpn.helper.plist"

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

    public var config: String?

    public var setDNS: Bool?

    public var killSwitch: Bool?

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

    public var lastHandshake: Int
    public var rxBytes: Int64
    public var txBytes: Int64
    public var endpoint: String?

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
