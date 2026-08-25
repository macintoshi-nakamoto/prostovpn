import Foundation

signal(SIGPIPE, SIG_IGN)

let tunnel = Tunnel()

SystemNetwork.restoreDNS()
SystemNetwork.removeBlackhole()

let ownerUID: uid_t? = {
    let path = URL(fileURLWithPath: HelperPaths.supportDirectory).appendingPathComponent("owner.uid")
    guard let text = try? String(contentsOf: path, encoding: .utf8),
          let value = UInt32(text.trimmingCharacters(in: .whitespacesAndNewlines))
    else { return nil }
    return uid_t(value)
}()

private func peerUID(of fd: Int32) -> uid_t? {
    var credentials = xucred()
    var length = socklen_t(MemoryLayout<xucred>.size)

    guard getsockopt(fd, 0, 1, &credentials, &length) == 0 else { return nil }
    guard credentials.cr_version == XUCRED_VERSION else { return nil }
    return credentials.cr_uid
}

private func isAllowed(_ fd: Int32) -> Bool {
    guard let uid = peerUID(of: fd) else { return false }
    if uid == 0 { return true }
    guard let ownerUID else { return false }
    return uid == ownerUID
}

private func handle(_ request: HelperRequest) -> HelperResponse {
    switch request.cmd {
    case .ping:
        return HelperResponse(ok: true, version: HelperPaths.version)

    case .up:
        guard let config = request.config, !config.isEmpty else {
            return HelperResponse(ok: false, error: "команде «подключить» нужна конфигурация")
        }
        do {
            let name = try tunnel.up(
                configText: config,
                setDNS: request.setDNS ?? true,
                killSwitch: request.killSwitch ?? false,
                bypass: request.bypass ?? []
            )
            return HelperResponse(
                ok: true,
                version: HelperPaths.version,
                status: HelperStatus(up: true, interfaceName: name)
            )
        } catch {
            return HelperResponse(ok: false, error: error.localizedDescription)
        }

    case .down:
        tunnel.down()
        return HelperResponse(ok: true, version: HelperPaths.version, status: tunnel.status())

    case .status:
        return HelperResponse(ok: true, version: HelperPaths.version, status: tunnel.status())
    }
}

private func serve(_ fd: Int32) {
    defer { close(fd) }

    guard isAllowed(fd) else {
        respond(fd, HelperResponse(ok: false, error: "доступ запрещён"))
        return
    }

    var timeout = timeval(tv_sec: 30, tv_usec: 0)
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))

    var data = Data()
    var buffer = [UInt8](repeating: 0, count: 8192)

    while data.count < 1_000_000 {
        let read = Darwin.read(fd, &buffer, buffer.count)
        if read <= 0 { break }
        data.append(contentsOf: buffer[0..<read])
        if data.last == 0x0a { break }
    }

    guard let request = try? JSONDecoder().decode(HelperRequest.self, from: data) else {
        respond(fd, HelperResponse(ok: false, error: "не удалось разобрать команду"))
        return
    }
    respond(fd, handle(request))
}

private func respond(_ fd: Int32, _ response: HelperResponse) {
    guard var payload = try? JSONEncoder().encode(response) else { return }
    payload.append(0x0a)
    payload.withUnsafeBytes { buffer in
        var sent = 0
        while sent < buffer.count {
            let written = write(fd, buffer.baseAddress!.advanced(by: sent), buffer.count - sent)
            if written <= 0 { return }
            sent += written
        }
    }
}

private func listenSocket(at path: String) -> Int32 {
    unlink(path)

    let fd = socket(AF_UNIX, SOCK_STREAM, 0)
    guard fd >= 0 else {
        FileHandle.standardError.write(Data("не удалось создать сокет\n".utf8))
        exit(1)
    }

    var address = sockaddr_un()
    address.sun_family = sa_family_t(AF_UNIX)
    let maxLength = MemoryLayout.size(ofValue: address.sun_path)
    withUnsafeMutablePointer(to: &address.sun_path) { pointer in
        pointer.withMemoryRebound(to: CChar.self, capacity: maxLength) { destination in
            _ = strcpy(destination, path)
        }
    }
    address.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)

    let bound = withUnsafePointer(to: &address) { pointer in
        pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockaddrPointer in
            bind(fd, sockaddrPointer, socklen_t(MemoryLayout<sockaddr_un>.size))
        }
    }
    guard bound == 0 else {
        FileHandle.standardError.write(Data("не удалось занять \(path)\n".utf8))
        exit(1)
    }

    chmod(path, 0o666)
    guard listen(fd, 16) == 0 else {
        FileHandle.standardError.write(Data("не удалось начать слушать \(path)\n".utf8))
        exit(1)
    }
    return fd
}

let server = listenSocket(at: HelperPaths.socket)
let workers = DispatchQueue(label: "com.prostovpn.helper.workers", attributes: .concurrent)

while true {
    let client = accept(server, nil, nil)
    if client < 0 {
        if errno == EINTR { continue }
        break
    }

    workers.async { serve(client) }
}
