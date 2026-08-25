import Foundation

enum SystemNetwork {
    static func configureInterface(_ name: String, addresses: [String], mtu: Int) throws {
        for address in addresses {
            let parts = address.components(separatedBy: "/")
            let ip = parts[0]
            let prefix = parts.count > 1 ? parts[1] : (ip.contains(":") ? "128" : "32")

            if ip.contains(":") {
                try Shell.run(Shell.ifconfig, [name, "inet6", "\(ip)/\(prefix)", "alias"])
            } else {
                try Shell.run(Shell.ifconfig, [name, "inet", ip, ip, "alias"])
            }
        }
        try Shell.run(Shell.ifconfig, [name, "mtu", String(mtu)])
        try Shell.run(Shell.ifconfig, [name, "up"])
    }

    struct DefaultRoute {
        var gateway: String?
        var interfaceName: String

        var routeArguments: [String] {
            if let gateway, !gateway.isEmpty, !gateway.hasPrefix("link#") {
                return ["-gateway", gateway]
            }
            return ["-interface", interfaceName]
        }
    }

    static func currentDefaultRoute(ipv6: Bool = false) -> DefaultRoute? {
        guard let output = Shell.tryRun(Shell.route, ["-n", "get", ipv6 ? "-inet6" : "-inet", "default"]) else {
            return nil
        }
        var gateway: String?
        var interfaceName: String?
        for line in output.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix("gateway:") {
                gateway = String(trimmed.dropFirst("gateway:".count)).trimmingCharacters(in: .whitespaces)
            }
            if trimmed.hasPrefix("interface:") {
                interfaceName = String(trimmed.dropFirst("interface:".count)).trimmingCharacters(in: .whitespaces)
            }
        }
        guard let interfaceName else { return nil }
        return DefaultRoute(gateway: gateway, interfaceName: interfaceName)
    }

    static func addDirectRoute(_ destination: String, via exit: DefaultRoute) {
        let ipv6 = destination.contains(":")
        let family = ipv6 ? "-inet6" : "-inet"
        let isNetwork = destination.contains("/")

        var arguments = ["-q", "-n", "add", family]
        if isNetwork { arguments.append("-net") }
        arguments.append(destination)
        arguments.append(contentsOf: exit.routeArguments)

        removeDirectRoute(destination)
        Shell.tryRun(Shell.route, arguments)
    }

    static func removeDirectRoute(_ destination: String) {
        let family = destination.contains(":") ? "-inet6" : "-inet"
        var arguments = ["-q", "-n", "delete", family]
        if destination.contains("/") { arguments.append("-net") }
        arguments.append(destination)
        Shell.tryRun(Shell.route, arguments)
    }

    static func addRoutes(_ allowedIPs: [String], interfaceName: String) {
        for allowed in allowedIPs {
            switch allowed {
            case "0.0.0.0/0":
                add("-inet", "0.0.0.0/1", interfaceName)
                add("-inet", "128.0.0.0/1", interfaceName)
            case "::/0":
                add("-inet6", "::/1", interfaceName)
                add("-inet6", "8000::/1", interfaceName)
            default:
                add(allowed.contains(":") ? "-inet6" : "-inet", allowed, interfaceName)
            }
        }
    }

    private static func add(_ family: String, _ destination: String, _ interfaceName: String) {
        Shell.tryRun(Shell.route, ["-q", "-n", "add", family, "-net", destination, "-interface", interfaceName])
    }

    static func installBlackhole(ipv6: Bool) {
        Shell.tryRun(Shell.route, ["-q", "-n", "add", "-inet", "-net", "0.0.0.0/1", "-blackhole", "127.0.0.1"])
        Shell.tryRun(Shell.route, ["-q", "-n", "add", "-inet", "-net", "128.0.0.0/1", "-blackhole", "127.0.0.1"])
        if ipv6 {
            Shell.tryRun(Shell.route, ["-q", "-n", "add", "-inet6", "-net", "::/1", "-blackhole", "::1"])
            Shell.tryRun(Shell.route, ["-q", "-n", "add", "-inet6", "-net", "8000::/1", "-blackhole", "::1"])
        }
    }

    static func removeBlackhole() {
        Shell.tryRun(Shell.route, ["-q", "-n", "delete", "-inet", "-net", "0.0.0.0/1"])
        Shell.tryRun(Shell.route, ["-q", "-n", "delete", "-inet", "-net", "128.0.0.0/1"])
        Shell.tryRun(Shell.route, ["-q", "-n", "delete", "-inet6", "-net", "::/1"])
        Shell.tryRun(Shell.route, ["-q", "-n", "delete", "-inet6", "-net", "8000::/1"])
    }

    struct DNSBackup: Codable {
        var services: [String: [String]]
    }

    private static var backupURL: URL {
        URL(fileURLWithPath: HelperPaths.supportDirectory).appendingPathComponent("dns-backup.json")
    }

    static func applyDNS(_ servers: [String]) {
        guard !servers.isEmpty else { return }
        let services = enabledNetworkServices()
        guard !services.isEmpty else { return }

        if loadDNSBackup() == nil {
            var saved: [String: [String]] = [:]
            for service in services {
                saved[service] = currentDNS(for: service)
            }
            storeDNSBackup(DNSBackup(services: saved))
        }

        for service in services {
            Shell.tryRun(Shell.networksetup, ["-setdnsservers", service] + servers)
        }
    }

    static func restoreDNS() {
        guard let backup = loadDNSBackup() else { return }
        for (service, servers) in backup.services {
            let arguments = servers.isEmpty ? ["Empty"] : servers
            Shell.tryRun(Shell.networksetup, ["-setdnsservers", service] + arguments)
        }
        try? FileManager.default.removeItem(at: backupURL)
    }

    private static func enabledNetworkServices() -> [String] {
        guard let output = Shell.tryRun(Shell.networksetup, ["-listallnetworkservices"]) else { return [] }
        return output.components(separatedBy: .newlines)
            .dropFirst()
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty && !$0.hasPrefix("*") }
    }

    private static func currentDNS(for service: String) -> [String] {
        guard let output = Shell.tryRun(Shell.networksetup, ["-getdnsservers", service]) else { return [] }
        let lines = output.components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }

        return lines.allSatisfy { WGQuick.isIPAddress($0) } ? lines : []
    }

    private static func storeDNSBackup(_ backup: DNSBackup) {
        try? FileManager.default.createDirectory(
            atPath: HelperPaths.supportDirectory,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o755]
        )
        guard let data = try? JSONEncoder().encode(backup) else { return }
        try? data.write(to: backupURL, options: .atomic)
    }

    private static func loadDNSBackup() -> DNSBackup? {
        guard let data = try? Data(contentsOf: backupURL) else { return nil }
        return try? JSONDecoder().decode(DNSBackup.self, from: data)
    }

    static func resolveEndpoint(_ endpoint: String) -> String? {
        guard let (host, port) = WGQuick.splitEndpoint(endpoint) else { return nil }
        if WGQuick.isIPAddress(host) {
            return host.contains(":") ? "[\(host)]:\(port)" : "\(host):\(port)"
        }

        var hints = addrinfo(
            ai_flags: 0,
            ai_family: AF_UNSPEC,
            ai_socktype: SOCK_DGRAM,
            ai_protocol: IPPROTO_UDP,
            ai_addrlen: 0,
            ai_canonname: nil,
            ai_addr: nil,
            ai_next: nil
        )
        var result: UnsafeMutablePointer<addrinfo>?
        guard getaddrinfo(host, port, &hints, &result) == 0, let head = result else { return nil }
        defer { freeaddrinfo(head) }

        var node: UnsafeMutablePointer<addrinfo>? = head

        var ipv6Fallback: String?
        while let current = node {
            var buffer = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            if getnameinfo(
                current.pointee.ai_addr,
                current.pointee.ai_addrlen,
                &buffer, socklen_t(buffer.count),
                nil, 0,
                NI_NUMERICHOST
            ) == 0 {
                let address = String(cString: buffer)
                if current.pointee.ai_family == AF_INET {
                    return "\(address):\(port)"
                }
                if ipv6Fallback == nil {
                    ipv6Fallback = "[\(address.components(separatedBy: "%")[0])]:\(port)"
                }
            }
            node = current.pointee.ai_next
        }
        return ipv6Fallback
    }
}
