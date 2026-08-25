import Foundation

enum UAPI {
    static let socketDirectory = "/var/run/amneziawg"

    static func socketPath(for interfaceName: String) -> String {
        "\(socketDirectory)/\(interfaceName).sock"
    }

    struct Error: LocalizedError {
        let message: String
        var errorDescription: String? { message }
    }

    static func exchange(interfaceName: String, request: String) throws -> String {
        let path = socketPath(for: interfaceName)
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { throw Error(message: "не удалось создать сокет UAPI") }
        defer { close(fd) }

        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        let maxLength = MemoryLayout.size(ofValue: address.sun_path)
        guard path.utf8.count < maxLength else { throw Error(message: "слишком длинный путь к сокету") }
        withUnsafeMutablePointer(to: &address.sun_path) { pointer in
            pointer.withMemoryRebound(to: CChar.self, capacity: maxLength) { destination in
                _ = strcpy(destination, path)
            }
        }
        address.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)

        let connected = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockaddrPointer in
                connect(fd, sockaddrPointer, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard connected == 0 else {
            throw Error(message: "движок не отвечает на \(path)")
        }

        var timeout = timeval(tv_sec: 5, tv_usec: 0)
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))

        let payload = Array(request.utf8)
        var sent = 0
        while sent < payload.count {
            let written = payload.withUnsafeBytes { buffer -> Int in
                write(fd, buffer.baseAddress!.advanced(by: sent), payload.count - sent)
            }
            guard written > 0 else { throw Error(message: "не удалось передать команду движку") }
            sent += written
        }

        var response = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while true {
            let read = Darwin.read(fd, &buffer, buffer.count)
            if read <= 0 { break }
            response.append(contentsOf: buffer[0..<read])

            if response.count >= 2, response.suffix(2) == Data([0x0a, 0x0a]) { break }
        }
        return String(data: response, encoding: .utf8) ?? ""
    }

    struct Snapshot {
        var lastHandshake: Int = 0
        var rxBytes: Int64 = 0
        var txBytes: Int64 = 0
        var endpoint: String?
    }

    static func snapshot(interfaceName: String) -> Snapshot? {
        guard let response = try? exchange(interfaceName: interfaceName, request: "get=1\n\n") else { return nil }
        var snapshot = Snapshot()
        for line in response.components(separatedBy: .newlines) {
            guard let eq = line.firstIndex(of: "=") else { continue }
            let key = String(line[..<eq])
            let value = String(line[line.index(after: eq)...])
            switch key {
            case "last_handshake_time_sec":
                snapshot.lastHandshake = max(snapshot.lastHandshake, Int(value) ?? 0)
            case "rx_bytes":
                snapshot.rxBytes += Int64(value) ?? 0
            case "tx_bytes":
                snapshot.txBytes += Int64(value) ?? 0
            case "endpoint":
                snapshot.endpoint = value
            default:
                continue
            }
        }
        return snapshot
    }
}
