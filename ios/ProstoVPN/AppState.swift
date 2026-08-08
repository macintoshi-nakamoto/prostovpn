import SwiftUI
import Combine
import Compression
import ActivityKit

struct ServerInfo: Codable, Equatable {
    var host: String
    var country: String?
    var city: String?
    var countryCode: String?
}

struct DemoServer {
    let flag: String
    let nameRu: String
    let nameEn: String
    let cityRu: String
    let cityEn: String
    let ping: Int
}

struct DisplayServer: Equatable {
    let flag: String
    let name: String
    let sub: String
}

struct TunnelFile: Codable, Identifiable, Equatable {
    var id = UUID()
    var name: String
    var count: Int
    var isDefault = false
}

@MainActor
final class AppState: ObservableObject {

    enum Phase {
        case off, connecting, on
    }

    @Published var phase: Phase = .off
    @Published var seconds: Int = 0

    @Published var lang: String {
        didSet { UserDefaults.standard.set(lang, forKey: Keys.lang) }
    }
    var t: L10n { L10n.of(lang) }

    @Published var importedServer: ServerInfo?
    @Published var isGuest: Bool {
        didSet { UserDefaults.standard.set(isGuest, forKey: Keys.guest) }
    }
    var isLoggedIn: Bool { importedServer != nil || isGuest }

    @Published var selectedServerIndex: Int {
        didSet {
            UserDefaults.standard.set(selectedServerIndex, forKey: Keys.selectedServer)
            if oldValue != selectedServerIndex {
                restartLiveActivityIfNeeded()
            }
        }
    }

    @Published var tunnelFiles: [TunnelFile] {
        didSet { persistTunnelFiles() }
    }
    @Published var activeTunnelFileID: UUID? {
        didSet { UserDefaults.standard.set(activeTunnelFileID?.uuidString, forKey: Keys.activeTunnelFile) }
    }

    private var timer: Timer?
    private var connectTask: Task<Void, Never>?
    private var liveActivity: Activity<ConnectionAttributes>?
    private var connectedAt: Date?
    var didAutoConnect = false

    private enum Keys {
        static let server = "prosto.server"
        static let accessKey = "prosto.accessKey"
        static let guest = "prosto.guest"
        static let lang = "prosto.lang"
        static let selectedServer = "prosto.selectedServer"
        static let tunnelFiles = "prosto.tunnelFiles"
        static let activeTunnelFile = "prosto.activeTunnelFile"
    }

    static let demoServers: [DemoServer] = [
        DemoServer(flag: "🇳🇱", nameRu: "Нидерланды", nameEn: "Netherlands", cityRu: "Амстердам", cityEn: "Amsterdam", ping: 34),
        DemoServer(flag: "🇸🇪", nameRu: "Швеция", nameEn: "Sweden", cityRu: "Стокгольм", cityEn: "Stockholm", ping: 41),
        DemoServer(flag: "🇩🇪", nameRu: "Германия", nameEn: "Germany", cityRu: "Франкфурт", cityEn: "Frankfurt", ping: 48),
    ]

    init() {
        let defaults = UserDefaults.standard

        lang = defaults.string(forKey: Keys.lang) ?? "ru"
        isGuest = defaults.bool(forKey: Keys.guest)
        selectedServerIndex = defaults.integer(forKey: Keys.selectedServer)

        if let data = defaults.data(forKey: Keys.tunnelFiles),
           let saved = try? JSONDecoder().decode([TunnelFile].self, from: data),
           !saved.isEmpty {
            tunnelFiles = saved
        } else {
            tunnelFiles = [TunnelFile(name: "default_list.json", count: 214, isDefault: true)]
        }

        if let idString = defaults.string(forKey: Keys.activeTunnelFile),
           let id = UUID(uuidString: idString) {
            activeTunnelFileID = id
        }

        if let data = defaults.data(forKey: Keys.server),
           let saved = try? JSONDecoder().decode(ServerInfo.self, from: data) {
            importedServer = saved
        }

        if tunnelFiles.first(where: { $0.id == activeTunnelFileID }) == nil {
            activeTunnelFileID = tunnelFiles.first?.id
        }
        if selectedServerIndex >= displayServers().count {
            selectedServerIndex = 0
        }

        if importedServer != nil {
            refreshGeo()
        }

        Task {
            for orphan in Activity<ConnectionAttributes>.activities {
                await orphan.end(nil, dismissalPolicy: .immediate)
            }
        }
    }

    func displayServers() -> [DisplayServer] {
        let t = self.t
        if let s = importedServer {
            let flag = (s.countryCode?.isEmpty == false) ? flagEmoji(countryCode: s.countryCode!) : "🌐"
            let name = (s.country?.isEmpty == false) ? s.country! : s.host
            let sub = (s.city?.isEmpty == false) ? s.city! : s.host
            return [DisplayServer(flag: flag, name: name, sub: sub)]
        }
        return Self.demoServers.map { demo in
            DisplayServer(
                flag: demo.flag,
                name: lang == "en" ? demo.nameEn : demo.nameRu,
                sub: "\(lang == "en" ? demo.cityEn : demo.cityRu) · \(demo.ping) \(t.ms)"
            )
        }
    }

    var currentServer: DisplayServer? {
        let servers = displayServers()
        guard !servers.isEmpty else { return nil }
        return servers[min(selectedServerIndex, servers.count - 1)]
    }

    enum LoginError: LocalizedError {
        case badKey

        var errorDescription: String? {
            "badKey"
        }
    }

    func login(credentials: String) throws {
        let joined = credentials
            .components(separatedBy: .whitespacesAndNewlines)
            .joined()

        if joined.hasPrefix("vpn://") {
            guard let info = Self.extractServer(fromAccessKey: joined) else {
                throw LoginError.badKey
            }
            UserDefaults.standard.set(joined, forKey: Keys.accessKey)
            importedServer = info
            selectedServerIndex = 0
            persistServer()
            refreshGeo()
            return
        }

        isGuest = true
    }

    func loginAsGuest() {
        isGuest = true
    }

    func logout() {
        disconnect()
        importedServer = nil
        isGuest = false
        selectedServerIndex = 0
        UserDefaults.standard.removeObject(forKey: Keys.server)
        UserDefaults.standard.removeObject(forKey: Keys.accessKey)
    }

    private func persistServer() {
        guard let importedServer else { return }
        if let data = try? JSONEncoder().encode(importedServer) {
            UserDefaults.standard.set(data, forKey: Keys.server)
        }
    }

    func toggleConnection() {
        switch phase {
        case .connecting, .on:
            disconnect()
        case .off:
            phase = .connecting
            connectTask = Task { [weak self] in
                try? await Task.sleep(nanoseconds: 1_600_000_000)
                guard let self, !Task.isCancelled, self.phase == .connecting else { return }
                self.phase = .on
                self.startTimer()
                Haptics.success()
                self.startLiveActivity()
            }
        }
    }

    func disconnect() {
        connectTask?.cancel()
        connectTask = nil
        timer?.invalidate()
        timer = nil
        if phase == .on {
            Haptics.tap()
        }
        phase = .off
        seconds = 0
        connectedAt = nil
        endLiveActivity()
    }

    private func startLiveActivity() {
        guard ActivityAuthorizationInfo().areActivitiesEnabled else { return }

        for orphan in Activity<ConnectionAttributes>.activities where orphan.id != liveActivity?.id {
            Task { await orphan.end(nil, dismissalPolicy: .immediate) }
        }

        let attributes = ConnectionAttributes(
            serverName: currentServer?.name ?? "VPN",
            serverFlag: currentServer?.flag ?? "🌐",
            statusLabel: t.connected
        )
        let content = ActivityContent(
            state: ConnectionAttributes.ContentState(startedAt: connectedAt ?? Date()),
            staleDate: nil
        )
        liveActivity = try? Activity.request(attributes: attributes, content: content)
    }

    private func endLiveActivity() {
        guard let activity = liveActivity else { return }
        liveActivity = nil
        Task { await activity.end(nil, dismissalPolicy: .immediate) }
    }

    private func restartLiveActivityIfNeeded() {
        guard phase == .on else { return }
        endLiveActivity()
        startLiveActivity()
    }

    private func startTimer() {
        let started = Date()
        connectedAt = started
        seconds = 0
        let timer = Timer(timeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, let anchor = self.connectedAt else { return }
                let elapsed = Int(Date().timeIntervalSince(anchor))
                if elapsed != self.seconds {
                    self.seconds = elapsed
                }
            }
        }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    var formattedDuration: String {
        let h = seconds / 3600
        let m = (seconds % 3600) / 60
        let s = seconds % 60
        return h > 0
            ? String(format: "%d:%02d:%02d", h, m, s)
            : String(format: "%02d:%02d", m, s)
    }

    var activeTunnelFile: TunnelFile? {
        tunnelFiles.first { $0.id == activeTunnelFileID }
    }

    func selectTunnelFile(_ file: TunnelFile) {
        activeTunnelFileID = file.id
    }

    func addTunnelFile(from url: URL) throws {
        let secured = url.startAccessingSecurityScopedResource()
        defer {
            if secured { url.stopAccessingSecurityScopedResource() }
        }

        let data = try Data(contentsOf: url)
        let count = Self.entryCount(in: data, fileExtension: url.pathExtension)

        let dir = try tunnelDirectory()
        var name = url.lastPathComponent
        var attempt = 1
        while tunnelFiles.contains(where: { $0.name == name }) {
            let base = url.deletingPathExtension().lastPathComponent
            let ext = url.pathExtension.isEmpty ? "" : ".\(url.pathExtension)"
            name = "\(base)_\(attempt)\(ext)"
            attempt += 1
        }
        try data.write(to: dir.appendingPathComponent(name))

        let file = TunnelFile(name: name, count: count)
        tunnelFiles.append(file)
        activeTunnelFileID = file.id
    }

    func deleteTunnelFile(_ file: TunnelFile) {
        guard !file.isDefault else { return }
        tunnelFiles.removeAll { $0.id == file.id }
        if let dir = try? tunnelDirectory() {
            try? FileManager.default.removeItem(at: dir.appendingPathComponent(file.name))
        }
        if activeTunnelFileID == file.id {
            activeTunnelFileID = tunnelFiles.first?.id
        }
    }

    private func tunnelDirectory() throws -> URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let dir = docs.appendingPathComponent("Tunneling", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    private func persistTunnelFiles() {
        if let data = try? JSONEncoder().encode(tunnelFiles) {
            UserDefaults.standard.set(data, forKey: Keys.tunnelFiles)
        }
    }

    static func entryCount(in data: Data, fileExtension: String) -> Int {
        if fileExtension.lowercased() == "json",
           let object = try? JSONSerialization.jsonObject(with: data) {
            if let array = object as? [Any] { return array.count }
            if let dict = object as? [String: Any] { return dict.count }
        }
        guard let text = String(data: data, encoding: .utf8) else { return 0 }
        return text
            .components(separatedBy: .newlines)
            .filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
            .count
    }

    func refreshGeo() {
        guard let host = importedServer?.host, !host.isEmpty, importedServer?.country == nil else { return }
        guard let url = URL(string: "http://ip-api.com/json/\(host)?fields=status,country,countryCode,city&lang=ru") else { return }

        Task { [weak self] in
            guard let (data, _) = try? await URLSession.shared.data(from: url) else { return }
            guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  json["status"] as? String == "success" else { return }

            guard let self, var updated = self.importedServer, updated.host == host else { return }
            updated.country = json["country"] as? String
            updated.city = json["city"] as? String
            updated.countryCode = json["countryCode"] as? String
            self.importedServer = updated
            self.persistServer()
        }
    }

    static func extractServer(fromAccessKey key: String) -> ServerInfo? {
        let payload = String(key.dropFirst("vpn://".count))
        guard let data = decodeBase64Flexible(payload) else {
            return nil
        }

        if let text = String(data: data, encoding: .utf8),
           text.contains("[Interface]") || text.contains("[Peer]") {
            return ServerInfo(host: endpointHost(inConfigText: text) ?? "")
        }

        if let object = decodeQCompressedJson(data) {
            return ServerInfo(host: findHost(in: object) ?? "")
        }

        if let object = try? JSONSerialization.jsonObject(with: data) {
            return ServerInfo(host: findHost(in: object) ?? "")
        }

        return nil
    }

    private static func decodeBase64Flexible(_ payload: String) -> Data? {
        var base64 = payload
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        while base64.count % 4 != 0 {
            base64.append("=")
        }
        return Data(base64Encoded: base64)
    }

    private static func endpointHost(inConfigText text: String) -> String? {
        for line in text.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard trimmed.lowercased().hasPrefix("endpoint"),
                  let eqIndex = trimmed.firstIndex(of: "=") else { continue }

            var value = String(trimmed[trimmed.index(after: eqIndex)...])
                .trimmingCharacters(in: .whitespaces)

            if value.hasPrefix("[") {
                if let close = value.firstIndex(of: "]") {
                    value = String(value[value.index(after: value.startIndex)..<close])
                }
            } else if let colon = value.lastIndex(of: ":") {
                value = String(value[..<colon])
            }

            if !value.isEmpty {
                return value
            }
        }
        return nil
    }

    private static func decodeQCompressedJson(_ compressed: Data) -> Any? {
        guard compressed.count > 6 else { return nil }

        let expectedSize = compressed.prefix(4).reduce(0) { ($0 << 8) | Int($1) }
        guard expectedSize > 0, expectedSize < 10_000_000 else { return nil }

        let deflateBody = compressed.dropFirst(6)
        var output = Data(count: expectedSize)

        let decodedSize = output.withUnsafeMutableBytes { (outPtr: UnsafeMutableRawBufferPointer) -> Int in
            deflateBody.withUnsafeBytes { (inPtr: UnsafeRawBufferPointer) -> Int in
                guard let outBase = outPtr.baseAddress, let inBase = inPtr.baseAddress else { return 0 }
                return compression_decode_buffer(
                    outBase.assumingMemoryBound(to: UInt8.self), expectedSize,
                    inBase.assumingMemoryBound(to: UInt8.self), deflateBody.count,
                    nil, COMPRESSION_ZLIB
                )
            }
        }

        guard decodedSize > 0 else { return nil }
        return try? JSONSerialization.jsonObject(with: output.prefix(decodedSize))
    }

    private static func findHost(in object: Any) -> String? {
        if let dict = object as? [String: Any] {
            for key in ["hostName", "host"] {
                if let host = dict[key] as? String, !host.isEmpty {
                    return host
                }
            }
            for value in dict.values {
                if let host = findHost(in: value) {
                    return host
                }
            }
        } else if let array = object as? [Any] {
            for value in array {
                if let host = findHost(in: value) {
                    return host
                }
            }
        } else if let string = object as? String {
            if string.contains("[Interface]") || string.contains("Endpoint") {
                return endpointHost(inConfigText: string)
            }
        }
        return nil
    }
}
