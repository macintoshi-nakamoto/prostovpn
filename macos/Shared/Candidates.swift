import Foundation

struct Candidate: Equatable, CustomStringConvertible {
    let host: String
    let port: Int

    var description: String { "\(host):\(port)" }
}

enum Candidates {
    private static let endpointLine = try! NSRegularExpression(
        pattern: #"(?im)^([ \t]*Endpoint[ \t]*=[ \t]*)(\S+?)(?::(\d+))?[ \t]*$"#
    )

    static func port(in config: String) -> Int? {
        let range = NSRange(config.startIndex..., in: config)
        guard let match = endpointLine.firstMatch(in: config, range: range),
              match.numberOfRanges > 3,
              let portRange = Range(match.range(at: 3), in: config)
        else { return nil }
        return Int(config[portRange])
    }

    static func host(in config: String) -> String? {
        let range = NSRange(config.startIndex..., in: config)
        guard let match = endpointLine.firstMatch(in: config, range: range),
              let hostRange = Range(match.range(at: 2), in: config)
        else { return nil }
        return String(config[hostRange])
    }

    static func with(config: String, port: Int) -> String {
        let range = NSRange(config.startIndex..., in: config)
        return endpointLine.stringByReplacingMatches(
            in: config, range: range, withTemplate: "$1$2:\(port)"
        )
    }

    static func order(config: String, remembered: Int?, alternatives: [Int]) -> [Candidate] {
        guard let host = host(in: config), !host.isEmpty else { return [] }
        var ports: [Int] = []
        if let remembered, remembered > 0 { ports.append(remembered) }
        if let configPort = port(in: config), configPort > 0, !ports.contains(configPort) {
            ports.append(configPort)
        }
        for port in alternatives where port > 0 && !ports.contains(port) {
            ports.append(port)
        }
        return ports.map { Candidate(host: host, port: $0) }
    }
}
