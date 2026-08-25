import Foundation

enum HelperClient {
    struct Unavailable: LocalizedError {
        let reason: String
        var errorDescription: String? { reason }
    }

    static func send(_ request: HelperRequest, timeout: TimeInterval = 30) throws -> HelperResponse {
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { throw Unavailable(reason: "не удалось открыть сокет") }
        defer { close(fd) }

        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        let maxLength = MemoryLayout.size(ofValue: address.sun_path)
        withUnsafeMutablePointer(to: &address.sun_path) { pointer in
            pointer.withMemoryRebound(to: CChar.self, capacity: maxLength) { destination in
                _ = strcpy(destination, HelperPaths.socket)
            }
        }
        address.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)

        let connected = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockaddrPointer in
                connect(fd, sockaddrPointer, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard connected == 0 else {
            throw Unavailable(reason: "служба подключения не отвечает")
        }

        var tv = timeval(tv_sec: Int(timeout), tv_usec: 0)
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, socklen_t(MemoryLayout<timeval>.size))
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, socklen_t(MemoryLayout<timeval>.size))

        var payload = try JSONEncoder().encode(request)
        payload.append(0x0a)
        try payload.withUnsafeBytes { buffer in
            var sent = 0
            while sent < buffer.count {
                let written = write(fd, buffer.baseAddress!.advanced(by: sent), buffer.count - sent)
                guard written > 0 else { throw Unavailable(reason: "команда не дошла до службы") }
                sent += written
            }
        }

        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 8192)
        while true {
            let read = Darwin.read(fd, &buffer, buffer.count)
            if read <= 0 { break }
            data.append(contentsOf: buffer[0..<read])
            if data.last == 0x0a { break }
        }

        guard !data.isEmpty else { throw Unavailable(reason: "служба закрыла соединение молча") }
        return try JSONDecoder().decode(HelperResponse.self, from: data)
    }

    static func isReady() -> Bool {
        guard let response = try? send(HelperRequest(cmd: .ping), timeout: 3) else { return false }
        return response.ok && response.version == HelperPaths.version
    }
}
