import Darwin
import Foundation

/*
 Запись маршрутов напрямую в ядро через PF_ROUTE.

 Список раздельного туннелирования — это восемь с половиной тысяч сетей.
 Через `/sbin/route` каждая стоит запуска процесса: полторы миллисекунды,
 то есть около тринадцати секунд на подключение и столько же на отключение.
 Маршрутный сокет делает то же самое за доли секунды одним дескриптором.

 Формат сообщения — заголовок rt_msghdr, следом адреса в порядке
 назначение → шлюз → маска, каждый выровнен по четыре байта.
 */
final class RouteSocket {

    private let fd: Int32
    private var sequence: Int32 = 0

    init?() {
        fd = socket(PF_ROUTE, SOCK_RAW, 0)
        guard fd >= 0 else { return nil }

        // Ядро по умолчанию возвращает отправителю копию каждого сообщения.
        // Нам она не нужна, а непрочитанные копии переполняют приёмный буфер
        // и добавление начинает падать с ENOBUFS на середине списка.
        var off: Int32 = 0
        setsockopt(fd, SOL_SOCKET, SO_USELOOPBACK, &off, socklen_t(MemoryLayout<Int32>.size))
    }

    deinit {
        close(fd)
    }

    /// Куда направить маршрут.
    enum Exit {
        /// Через адрес шлюза — обычная сеть с маршрутизатором.
        case gateway(in_addr)
        /// Через интерфейс — point-to-point, у которого адреса шлюза нет.
        case interfaceIndex(UInt16)
    }

    enum Operation {
        case add
        case remove

        var messageType: UInt8 {
            self == .add ? UInt8(RTM_ADD) : UInt8(RTM_DELETE)
        }
    }

    /// Итог пакетной операции: сколько получилось и на чём споткнулись.
    struct Outcome {
        var applied = 0
        var skipped = 0
        var firstError: String?
    }

    /// Прописывает или снимает сразу весь список.
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

    // MARK: - Одно сообщение

    private enum SendResult {
        case success
        case failure(String)
    }

    /// Готовое сообщение для ядра.
    ///
    /// Вынесено отдельно, чтобы раскладку можно было проверить без root:
    /// тем же кодом собирается RTM_GET, а на него ядро отвечает и обычному
    /// пользователю — и молча проглотит только правильный формат.
    func rawMessage(type: UInt8, route: IPv4Route, via exit: Exit?, sequence: Int32) -> [UInt8] {
        let isHost = route.prefix == 32
        var flags = RTF_UP | RTF_STATIC
        if case .gateway? = exit { flags |= RTF_GATEWAY }
        if isHost { flags |= RTF_HOST }

        // Маску для маршрута до одного адреса не передают: хватает RTF_HOST.
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
            // Маршрут уже стоит — цели это не мешает.
            return .success
        case ESRCH where operation == .remove:
            // Снимать нечего: кто-то убрал раньше нас.
            return .success
        default:
            return .failure(String(cString: strerror(errno)))
        }
    }

    // MARK: - Сборка адресов

    /// Адреса в сообщении выровнены по границе четырёх байт.
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

/// Сеть IPv4, приведённая к адресу сети и маске.
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

        // Ядро отвергает маршрут, у которого в адресе есть биты вне маски,
        // поэтому «10.0.0.5/24» приводим к «10.0.0.0/24» сами.
        var network = in_addr()
        network.s_addr = address.s_addr & mask.s_addr

        self.network = network
        self.mask = mask
        self.prefix = prefix
    }
}
