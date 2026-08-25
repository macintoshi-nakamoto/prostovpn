import Foundation
import Compression

struct AccessKey {
    var config: String
    var host: String?
}

enum AccessKeyParser {
    static func parse(_ input: String) -> AccessKey? {
        let trimmed = input.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { return nil }

        if trimmed.contains("[Interface]") {
            return AccessKey(config: trimmed, host: endpointHost(in: trimmed))
        }

        guard trimmed.lowercased().hasPrefix("vpn://") else { return nil }

        let payload = trimmed.dropFirst("vpn://".count)
            .components(separatedBy: .whitespacesAndNewlines)
            .joined()
        guard let data = base64Data(payload) else { return nil }

        if let object = decompressedJSON(data) ?? (try? JSONSerialization.jsonObject(with: data)),
           let config = findConfig(in: object) {
            return AccessKey(config: config, host: findHost(in: object) ?? endpointHost(in: config))
        }

        if let text = String(data: data, encoding: .utf8), text.contains("[Interface]") {
            return AccessKey(config: text, host: endpointHost(in: text))
        }

        return nil
    }

    private static func base64Data(_ payload: some StringProtocol) -> Data? {
        var base64 = String(payload)
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        while base64.count % 4 != 0 { base64.append("=") }
        return Data(base64Encoded: base64)
    }

    private static func decompressedJSON(_ compressed: Data) -> Any? {
        guard compressed.count > 6 else { return nil }
        let expected = compressed.prefix(4).reduce(0) { ($0 << 8) | Int($1) }
        guard expected > 0, expected < 10_000_000 else { return nil }

        let body = compressed.dropFirst(6)
        var output = Data(count: expected)
        let size = output.withUnsafeMutableBytes { out -> Int in
            body.withUnsafeBytes { input -> Int in
                guard let outBase = out.baseAddress, let inBase = input.baseAddress else { return 0 }
                return compression_decode_buffer(
                    outBase.assumingMemoryBound(to: UInt8.self), expected,
                    inBase.assumingMemoryBound(to: UInt8.self), body.count,
                    nil, COMPRESSION_ZLIB
                )
            }
        }
        guard size > 0 else { return nil }
        return try? JSONSerialization.jsonObject(with: output.prefix(size))
    }

    private static func findConfig(in object: Any) -> String? {
        if let dictionary = object as? [String: Any] {
            if let raw = dictionary["last_config"] as? String {
                if let nested = raw.data(using: .utf8),
                   let inner = try? JSONSerialization.jsonObject(with: nested),
                   let config = findConfig(in: inner) {
                    return config
                }
                if raw.contains("[Interface]") { return raw }
            }
            if let config = dictionary["config"] as? String, config.contains("[Interface]") {
                return config
            }
            for value in dictionary.values {
                if let config = findConfig(in: value) { return config }
            }
        } else if let array = object as? [Any] {
            for value in array {
                if let config = findConfig(in: value) { return config }
            }
        } else if let text = object as? String, text.contains("[Interface]") {
            return text
        }
        return nil
    }

    private static func findHost(in object: Any) -> String? {
        if let dictionary = object as? [String: Any] {
            for key in ["hostName", "host"] {
                if let host = dictionary[key] as? String, !host.isEmpty { return host }
            }
            for value in dictionary.values {
                if let host = findHost(in: value) { return host }
            }
        } else if let array = object as? [Any] {
            for value in array {
                if let host = findHost(in: value) { return host }
            }
        }
        return nil
    }

    static func endpointHost(in config: String) -> String? {
        for line in config.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard trimmed.lowercased().hasPrefix("endpoint"),
                  let eq = trimmed.firstIndex(of: "=") else { continue }
            let value = trimmed[trimmed.index(after: eq)...].trimmingCharacters(in: .whitespaces)
            guard let (host, _) = WGQuick.splitEndpoint(value) else { continue }
            if !host.isEmpty { return host }
        }
        return nil
    }
}
