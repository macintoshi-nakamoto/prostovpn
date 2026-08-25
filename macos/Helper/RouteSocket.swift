import Darwin
import Foundation

final class RouteSocket {
    private let fd: Int32
    private var sequence: Int32 = 0

    init?() {
        fd = socket(PF_ROUTE, SOCK_RAW, 0)
        guard fd >= 0 else { return nil }

        var off: Int32 = 0
        setsockopt(fd, SOL_SOCKET, SO_USELOOPBACK, &off, socklen_t(MemoryLayout<Int32>.size))
    }

    deinit {
        close(fd)
    }

    enum Exit {
        case gateway(in_addr)

        case interfaceIndex(UInt16)
    }

    enum Operation {
        case add
        case remove

        var messageType: UInt8 {
            self == .add ? UInt8(RTM_ADD) : UInt8(RTM_DELETE)
        }
    }

    struct Outcome {
        var applied = 0
        var skipped = 0
        var firstError: String?
    }

    @discardableResult
    func apply(_ operation: Operation, networks: [String], via exit: Exit) -> Outcome {
        var outcome = Outcome()
        for cidr in networks {
            guard let route = IPv4Route(cidr: cidr) else {
                outcome.skipped += 1
                continue
            }
            switch send(operation, route: route, via: exit) {
            case .success:
                outcome.applied += 1
            case .failure(let message):
                outcome.skipped += 1
                if outcome.firstError == nil { outcome.firstError = "\(cidr): \(message)" }
            }
        }
        return outcome
    }

    private enum SendResult {
        case success
        case failure(String)
    }

    func rawMessage(type: UInt8, route: IPv4Route, via exit: Exit?, sequence: Int32) -> [UInt8] {
        let isHost = route.prefix == 32
        var flags = RTF_UP | RTF_STATIC
        if case .gateway? = exit { flags |= RTF_GATEWAY }
        if isHost { flags |= RTF_HOST }

        var addresses = RTA_DST
        if exit != nil { addresses |= RTA_GATEWAY }
        if !isHost { addresses |= RTA_NETMASK }

        var payload = [UInt8]()
        payload.append(contentsOf: bytes(of: socketAddress(route.network)))
        switch exit {
        case .gateway(let address):
            payload.append(contentsOf: bytes(of: socketAddress(address)))
        case .interfaceIndex(let index):
            payload.append(contentsOf: bytes(of: linkAddress(index: index)))
        case nil:
            break
        }
        if !isHost {
            payload.append(contentsOf: bytes(of: socketAddress(route.mask)))
        }

        var header = rt_msghdr()
        header.rtm_msglen = UInt16(MemoryLayout<rt_msghdr>.size + payload.count)
        header.rtm_version = UInt8(RTM_VERSION)
        header.rtm_type = type
        header.rtm_flags = flags
        header.rtm_addrs = addresses
        header.rtm_seq = sequence
        header.rtm_pid = 0
        header.rtm_errno = 0

        var message = [UInt8]()
        message.append(contentsOf: withUnsafeBytes(of: &header) { Array($0) })
        message.append(contentsOf: payload)
        return message
    }

    private func send(_ operation: Operation, route: IPv4Route, via exit: Exit) -> SendResult {
        sequence &+= 1
        let message = rawMessage(type: operation.messageType, route: route, via: exit, sequence: sequence)

        let written = message.withUnsafeBytes { write(fd, $0.baseAddress, $0.count) }
        if written >= 0 { return .success }

        switch errno {
        case EEXIST where operation == .add:

            return .success
        case ESRCH where operation == .remove:

            return .success
        default:
            return .failure(String(cString: strerror(errno)))
        }
    }

    private func bytes<T>(of value: T) -> [UInt8] {
        var copy = value
        let raw = withUnsafeBytes(of: &copy) { Array($0) }
        let padded = raw.count > 0 ? (1 + ((raw.count - 1) | (MemoryLayout<UInt32>.size - 1))) : MemoryLayout<UInt32>.size
        return raw + [UInt8](repeating: 0, count: padded - raw.count)
    }

    private func socketAddress(_ address: in_addr) -> sockaddr_in {
        var value = sockaddr_in()
        value.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        value.sin_family = sa_family_t(AF_INET)
        value.sin_addr = address
        return value
    }

    private func linkAddress(index: UInt16) -> sockaddr_dl {
        var value = sockaddr_dl()
        value.sdl_len = UInt8(MemoryLayout<sockaddr_dl>.size)
        value.sdl_family = UInt8(AF_LINK)
        value.sdl_index = index
        return value
    }
}

struct IPv4Route {
    let network: in_addr
    let mask: in_addr
    let prefix: Int

    init?(cidr: String) {
        let parts = cidr.components(separatedBy: "/")
        guard parts.count <= 2 else { return nil }

        var address = in_addr()
        guard inet_pton(AF_INET, parts[0], &address) == 1 else { return nil }

        let prefix = parts.count == 2 ? Int(parts[1]) ?? -1 : 32
        guard (0...32).contains(prefix) else { return nil }

        let maskBits: UInt32 = prefix == 0 ? 0 : ~UInt32(0) << (32 - prefix)
        var mask = in_addr()
        mask.s_addr = maskBits.bigEndian

        var network = in_addr()
        network.s_addr = address.s_addr & mask.s_addr

        self.network = network
        self.mask = mask
        self.prefix = prefix
    }
}
