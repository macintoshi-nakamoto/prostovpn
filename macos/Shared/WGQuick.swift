import Foundation

public struct WGPeer: Equatable, Sendable {
    public var publicKey: String
    public var presharedKey: String?
    public var allowedIPs: [String] = []
    public var endpoint: String?
    public var persistentKeepalive: Int?
}

public struct WGConfig: Equatable, Sendable {
    public var privateKey: String = ""
    public var addresses: [String] = []
    public var dns: [String] = []
    public var mtu: Int = 1280
    public var listenPort: Int?

    public var obfuscation: [(key: String, value: String)] = []
    public var peers: [WGPeer] = []

    public static func == (lhs: WGConfig, rhs: WGConfig) -> Bool {
        lhs.privateKey == rhs.privateKey
            && lhs.addresses == rhs.addresses
            && lhs.dns == rhs.dns
            && lhs.mtu == rhs.mtu
            && lhs.listenPort == rhs.listenPort
            && lhs.peers == rhs.peers
            && lhs.obfuscation.map(\.key) == rhs.obfuscation.map(\.key)
            && lhs.obfuscation.map(\.value) == rhs.obfuscation.map(\.value)
    }

    public var hasIPv6: Bool {
        addresses.contains { $0.contains(":") }
    }
}

public enum WGQuickError: LocalizedError {
    case noInterface
    case noPrivateKey
    case noAddress
    case noPeer
    case badKey(String)
    case badValue(String, String)

    public var errorDescription: String? {
        switch self {
        case .noInterface: return "в конфиге нет секции [Interface]"
        case .noPrivateKey: return "в конфиге нет PrivateKey"
        case .noAddress: return "в конфиге нет Address"
        case .noPeer: return "в конфиге нет ни одной секции [Peer]"
        case .badKey(let name): return "ключ \(name) не похож на ключ WireGuard"
        case .badValue(let name, let value): return "у поля \(name) неверное значение: \(value)"
        }
    }
}

public enum WGQuick {
    private static let obfuscationKeys: Set<String> = [
        "jc", "jmin", "jmax",
        "s1", "s2", "s3", "s4",
        "h1", "h2", "h3", "h4",
        "i1", "i2", "i3", "i4", "i5",
        "j1", "j2", "j3",
        "itime",
        "header_protection_key", "content_padding_addition",
    ]

    public static func parse(_ text: String) throws -> WGConfig {
        var config = WGConfig()
        var peers: [WGPeer] = []
        var current: WGPeer?
        var section = ""
        var sawInterface = false

        for rawLine in text.components(separatedBy: .newlines) {
            let line = rawLine.components(separatedBy: "#")[0]
                .components(separatedBy: ";")[0]
                .trimmingCharacters(in: .whitespaces)
            if line.isEmpty { continue }

            if line.hasPrefix("[") {
                if let peer = current {
                    peers.append(peer)
                    current = nil
                }
                section = line.trimmingCharacters(in: CharacterSet(charactersIn: "[]")).lowercased()
                if section == "interface" { sawInterface = true }
                if section == "peer" { current = WGPeer(publicKey: "") }
                continue
            }

            guard let eq = line.firstIndex(of: "=") else { continue }
            let key = line[..<eq].trimmingCharacters(in: .whitespaces)
            let value = line[line.index(after: eq)...].trimmingCharacters(in: .whitespaces)
            if value.isEmpty { continue }

            switch section {
            case "interface":
                try applyInterface(key: key, value: value, to: &config)
            case "peer":
                guard current != nil else { continue }
                try applyPeer(key: key, value: value, to: &current!)
            default:
                continue
            }
        }

        if let peer = current { peers.append(peer) }
        config.peers = peers

        guard sawInterface else { throw WGQuickError.noInterface }
        guard !config.privateKey.isEmpty else { throw WGQuickError.noPrivateKey }
        guard !config.addresses.isEmpty else { throw WGQuickError.noAddress }
        guard !config.peers.isEmpty else { throw WGQuickError.noPeer }

        return config
    }

    private static func applyInterface(key: String, value: String, to config: inout WGConfig) throws {
        switch key.lowercased() {
        case "privatekey":
            guard hexKey(fromBase64: value) != nil else { throw WGQuickError.badKey("PrivateKey") }
            config.privateKey = value
        case "address":
            config.addresses = splitList(value)
        case "dns":

            config.dns = splitList(value).filter { isIPAddress($0) }
        case "mtu":
            guard let mtu = Int(value), mtu >= 576, mtu <= 9000 else {
                throw WGQuickError.badValue("MTU", value)
            }
            config.mtu = mtu
        case "listenport":
            config.listenPort = Int(value)
        case "table", "preup", "postup", "predown", "postdown", "savedconfig", "fwmark":

            break
        default:
            let name = key.lowercased()
            if obfuscationKeys.contains(name) {
                config.obfuscation.append((key: name, value: value))
            }
        }
    }

    private static func applyPeer(key: String, value: String, to peer: inout WGPeer) throws {
        switch key.lowercased() {
        case "publickey":
            guard hexKey(fromBase64: value) != nil else { throw WGQuickError.badKey("PublicKey") }
            peer.publicKey = value
        case "presharedkey":
            guard hexKey(fromBase64: value) != nil else { throw WGQuickError.badKey("PresharedKey") }
            peer.presharedKey = value
        case "allowedips":
            peer.allowedIPs = splitList(value)
        case "endpoint":
            peer.endpoint = value
        case "persistentkeepalive":
            peer.persistentKeepalive = Int(value)
        default:
            break
        }
    }

    public static func uapiPayload(_ config: WGConfig, resolvedEndpoints resolved: [String: String]) -> String {
        var lines: [String] = []
        lines.append("private_key=\(hexKey(fromBase64: config.privateKey) ?? "")")
        if let port = config.listenPort {
            lines.append("listen_port=\(port)")
        }
        for item in config.obfuscation {
            lines.append("\(item.key)=\(item.value)")
        }

        lines.append("replace_peers=true")

        for peer in config.peers {
            lines.append("public_key=\(hexKey(fromBase64: peer.publicKey) ?? "")")
            if let psk = peer.presharedKey, let hex = hexKey(fromBase64: psk) {
                lines.append("preshared_key=\(hex)")
            }
            if let endpoint = peer.endpoint, let address = resolved[endpoint] {
                lines.append("endpoint=\(address)")
            }
            if let keepalive = peer.persistentKeepalive {
                lines.append("persistent_keepalive_interval=\(keepalive)")
            }
            lines.append("replace_allowed_ips=true")
            for allowed in peer.allowedIPs {
                lines.append("allowed_ip=\(allowed)")
            }
        }

        return "set=1\n" + lines.joined(separator: "\n") + "\n\n"
    }

    public static func splitList(_ value: String) -> [String] {
        value.components(separatedBy: CharacterSet(charactersIn: ", \t"))
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
    }

    public static func hexKey(fromBase64 value: String) -> String? {
        guard let data = Data(base64Encoded: value), data.count == 32 else { return nil }
        return data.map { String(format: "%02x", $0) }.joined()
    }

    public static func isIPAddress(_ value: String) -> Bool {
        var v4 = in_addr()
        if inet_pton(AF_INET, value, &v4) == 1 { return true }
        var v6 = in6_addr()
        return inet_pton(AF_INET6, value, &v6) == 1
    }

    public static func splitEndpoint(_ endpoint: String) -> (host: String, port: String)? {
        if endpoint.hasPrefix("[") {
            guard let close = endpoint.firstIndex(of: "]") else { return nil }
            let host = String(endpoint[endpoint.index(after: endpoint.startIndex)..<close])
            let rest = endpoint[endpoint.index(after: close)...]
            guard rest.hasPrefix(":") else { return nil }
            return (host, String(rest.dropFirst()))
        }
        guard let colon = endpoint.lastIndex(of: ":") else { return nil }
        return (String(endpoint[..<colon]), String(endpoint[endpoint.index(after: colon)...]))
    }
}
