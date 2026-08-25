import SwiftUI
import Combine

@MainActor
final class AppState: ObservableObject {
    enum Phase: Equatable {
        case off
        case connecting
        case on
        case disconnecting
    }

    static let shared = AppState()

    @Published private(set) var phase: Phase = .off
    @Published private(set) var seconds: Int = 0
    @Published private(set) var servers: [PanelServer] = []
    @Published private(set) var subscription: PanelSubscription?
    @Published private(set) var account: PanelAccount?
    @Published private(set) var helperReady = false

    private var lastBringUpError: String?

    @Published private(set) var notice: String = ""

    @Published private(set) var signedOutReason: String = ""

    @Published var errorMessage: String?
    @Published var isBusy = false

    @Published var lang: String {
        didSet { defaults.set(lang, forKey: Keys.lang) }
    }

    @Published var selectedServerID: Int? {
        didSet { defaults.set(selectedServerID ?? -1, forKey: Keys.selectedServer) }
    }

    let updates: UpdateManager

    var t: L10n { L10n.of(lang) }

    var isLoggedIn: Bool { account != nil || !servers.isEmpty }

    var currentServer: PanelServer? {
        servers.first { $0.id == selectedServerID } ?? servers.first
    }

    func consumeSignedOutReason() -> String {
        let reason = signedOutReason
        signedOutReason = ""
        return reason
    }

    var useVPNDNS: Bool {
        get { defaults.object(forKey: Keys.dns) as? Bool ?? true }
        set { defaults.set(newValue, forKey: Keys.dns) }
    }

    var killSwitch: Bool {
        get { defaults.bool(forKey: Keys.killSwitch) }
        set { defaults.set(newValue, forKey: Keys.killSwitch) }
    }

    var autoReconnect: Bool {
        get {
            guard defaults.object(forKey: Keys.autoReconnect) != nil else { return true }
            return defaults.bool(forKey: Keys.autoReconnect)
        }
        set { defaults.set(newValue, forKey: Keys.autoReconnect) }
    }

    var splitTunnel: Bool {
        get { defaults.object(forKey: Keys.bypass) as? Bool ?? true }
        set { defaults.set(newValue, forKey: Keys.bypass) }
    }

    var autoConnect: Bool {
        get { defaults.bool(forKey: Keys.autoConnect) }
        set { defaults.set(newValue, forKey: Keys.autoConnect) }
    }

    let tunnelFiles = TunnelFiles()

    static let defaultPanelAddress = "https://prostovpn.cc"

    private let defaults = UserDefaults.standard
    private let panel: PanelClient
    private var token: String? {
        didSet { Keychain.set(token, for: Keys.token) }
    }

    private var timer: Timer?
    private var connectedAt: Date?
    private var watchdog: Task<Void, Never>?
    private var heartbeat: Task<Void, Never>?
    private var accountWatch: Task<Void, Never>?
    private var autoConnectTried = false
    private var cancellables = Set<AnyCancellable>()

    private let accountPollSeconds: UInt64 = 60

    private enum Keys {
        static let lang = "prosto.lang"
        static let selectedServer = "prosto.selectedServer"
        static let dns = "prosto.dns"
        static let killSwitch = "prosto.killSwitch"
        static let bypass = "prosto.bypassRussianServices"
        static let autoConnect = "prosto.autoconnect"
        static let autoReconnect = "prosto.autoReconnect"
        static let panel = "prosto.panel"
        static let token = "panel.token"
        static let servers = "panel.servers"
        static let account = "prosto.account"
        static let subscription = "prosto.subscription"
    }

    init() {
        let systemLanguage = Locale.preferredLanguages.first?.hasPrefix("ru") == true ? "ru" : "en"
        lang = defaults.string(forKey: Keys.lang) ?? systemLanguage

        let saved = defaults.integer(forKey: Keys.selectedServer)
        selectedServerID = saved == 0 || saved == -1 ? nil : saved

        defaults.removeObject(forKey: Keys.panel)
        let client = PanelClient(baseURL: URL(string: Self.defaultPanelAddress)!)
        panel = client
        updates = UpdateManager(panel: client)

        token = Keychain.get(Keys.token)
        account = loadCachedAccount()
        subscription = loadCachedSubscription()
        servers = loadCachedServers()
        if selectedServerID == nil { selectedServerID = servers.first?.id }

        updates.objectWillChange
            .sink { [weak self] in self?.objectWillChange.send() }
            .store(in: &cancellables)

        refreshHelperState()
        syncPhaseWithHelper()
        startAccountWatch()

        updates.check()
    }

    func refreshHelperState() {
        Task.detached(priority: .userInitiated) {
            let ready = HelperClient.isReady()
            await MainActor.run { self.helperReady = ready }
        }
    }

    func installHelper() {
        isBusy = true
        Task.detached(priority: .userInitiated) {
            do {
                try HelperInstaller.install()
                await MainActor.run {
                    self.helperReady = true
                    self.isBusy = false
                }
            } catch is HelperInstaller.Cancelled {
                await MainActor.run { self.isBusy = false }
            } catch {
                await MainActor.run {
                    self.errorMessage = error.localizedDescription
                    self.isBusy = false
                }
            }
        }
    }

    private func syncPhaseWithHelper() {
        Task.detached(priority: .utility) {
            guard let response = try? HelperClient.send(HelperRequest(cmd: .status), timeout: 3),
                  let status = response.status, status.up
            else { return }
            await MainActor.run {
                self.phase = .on
                self.startTimer(from: Date())
                self.startWatchdog()
                self.startHeartbeat()
            }
        }
    }

    func login(login: String, password: String) async {
        errorMessage = nil
        isBusy = true
        defer { isBusy = false }

        do {
            let result = try await panel.login(
                login: login,
                password: password,
                deviceID: DeviceIdentity.installID,
                deviceName: DeviceIdentity.name
            )
            token = result.token
            apply(account: result.account)
            apply(subscription: result.subscription, notice: result.notice)
            apply(servers: result.servers)
            signedOutReason = ""
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func applyAccessKey(_ raw: String) -> Bool {
        guard let key = AccessKeyParser.parse(raw),
              (try? WGQuick.parse(key.config)) != nil
        else {
            errorMessage = t.errBadKey
            return false
        }

        let host = key.host ?? AccessKeyParser.endpointHost(in: key.config) ?? "—"
        let server = PanelServer(
            id: Self.accessKeyServerID,
            name: host,
            config: key.config,
            host: host
        )
        notice = ""
        apply(servers: [server])
        errorMessage = nil
        signedOutReason = ""
        refreshGeo(for: server)
        return true
    }

    static let accessKeyServerID = -1

    func refreshServers() async {
        guard let token else { return }
        do {
            let result = try await panel.servers(token: token)

            let lostAccess = result.servers.isEmpty && !servers.isEmpty
            apply(subscription: result.subscription, notice: result.notice)
            apply(servers: result.servers)
            if lostAccess, phase == .on || phase == .connecting {
                await disconnect()
                errorMessage = result.notice?.nilIfEmpty ?? t.subscriptionOver
            }
        } catch let error as PanelError where error.revokesSession {
            await signOut(reason: t.noticeRemoteSignout)
            Notifier.shared.notify(
                .signedOut,
                title: t.notifSignedOutTitle,
                body: t.noticeRemoteSignout
            )
        } catch {}
    }

    private func startAccountWatch() {
        accountWatch?.cancel()
        let period = accountPollSeconds
        accountWatch = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: period * 1_000_000_000)
                guard let self else { return }

                await self.refreshServers()
            }
        }
    }

    func signOut(reason: String = "") async {
        await disconnect()
        if let token {
            await panel.logout(token: token)
        }
        token = nil
        account = nil
        subscription = nil
        servers = []
        selectedServerID = nil
        notice = ""
        errorMessage = nil
        autoConnectTried = true
        defaults.removeObject(forKey: Keys.account)
        defaults.removeObject(forKey: Keys.subscription)
        Keychain.remove(Keys.servers)

        signedOutReason = reason
    }

    private func apply(account value: PanelAccount) {
        account = value
        if let data = try? JSONEncoder().encode(value) {
            defaults.set(data, forKey: Keys.account)
        }
    }

    private func apply(subscription value: PanelSubscription, notice text: String?) {
        subscription = value

        notice = text?.nilIfEmpty ?? ""
        if let data = try? JSONEncoder().encode(value) {
            defaults.set(data, forKey: Keys.subscription)
        }
        announce(value)
    }

    private func announce(_ value: PanelSubscription) {
        if value.traffic_low, let left = value.traffic_left_bytes {
            Notifier.shared.notify(
                .trafficLow,
                title: t.notifTrafficTitle,
                body: t.trafficLow(t.bytes(left)),
                throttle: 12 * 3600
            )
        }
        if value.expires_soon, value.active, let days = value.days_left {
            Notifier.shared.notify(
                .expiresSoon,
                title: t.notifExpiresTitle,
                body: t.expiresSoon(t.days(days)),
                throttle: 12 * 3600
            )
        }
    }

    private func apply(servers list: [PanelServer]) {
        servers = list
        if let id = selectedServerID, list.contains(where: { $0.id == id }) {} else {
            selectedServerID = list.first?.id
        }
        cache(servers: list)
    }

    func setSplitTunnel(_ enabled: Bool) {
        guard enabled != splitTunnel else { return }
        splitTunnel = enabled
        reapplyRoutes()
    }

    func selectTunnelFile(_ file: TunnelFile) {
        guard tunnelFiles.activeID != file.id else { return }
        tunnelFiles.activeID = file.id
        if splitTunnel { reapplyRoutes() }
    }

    func addTunnelFile(from url: URL) throws {
        try tunnelFiles.add(from: url)
        if splitTunnel { reapplyRoutes() }
    }

    func removeTunnelFile(_ file: TunnelFile) {
        let wasActive = tunnelFiles.activeID == file.id
        tunnelFiles.remove(file)
        if splitTunnel && wasActive { reapplyRoutes() }
    }

    private func reapplyRoutes() {
        guard phase == .on else { return }
        Task {
            await disconnect()
            await connect()
        }
    }

    func toggle() {
        switch phase {
        case .off:
            Task { await connect() }
        case .on, .connecting:
            Task { await disconnect() }
        case .disconnecting:
            break
        }
    }

    func maybeAutoConnect() async {
        guard !autoConnectTried else { return }
        autoConnectTried = true
        guard autoConnect, phase == .off, currentServer != nil else { return }
        await connect()
    }

    func connect() async {
        guard phase == .off else { return }
        guard let server = currentServer else {
            errorMessage = notice.nilIfEmpty ?? t.noServersHint
            return
        }

        errorMessage = nil
        Notifier.shared.clear(.dropped)

        Notifier.shared.requestPermissionIfNeeded()

        if !helperReady {
            isBusy = true
            let installed: Result<Void, Error> = await Task.detached {
                do { try HelperInstaller.ensureInstalled(); return .success(()) }
                catch { return .failure(error) }
            }.value
            isBusy = false
            switch installed {
            case .success:
                helperReady = true
            case .failure(let error):
                if !(error is HelperInstaller.Cancelled) {
                    errorMessage = error.localizedDescription
                }
                return
            }
        }

        phase = .connecting

        let candidates = Candidates.order(
            config: server.config,
            remembered: rememberedPort(for: server.id),
            alternatives: server.alt_ports
        )
        let plan = candidates.isEmpty ? [Candidate(host: server.host, port: 0)] : candidates

        for (index, candidate) in plan.enumerated() {
            guard phase == .connecting else { return }

            let config = candidate.port > 0
                ? Candidates.with(config: server.config, port: candidate.port)
                : server.config

            if await bringUp(config: config) == false {
                phase = .off
                errorMessage = lastBringUpError ?? t.errTunnelFailed
                return
            }

            let budget = index == 0 ? 20 : 8
            let handshake = await waitForHandshake(seconds: budget)
            guard phase == .connecting else { return }

            if handshake {
                if candidate.port > 0 { rememberPort(candidate.port, for: server.id) }
                phase = .on
                startTimer(from: Date())
                startWatchdog()
                startHeartbeat()
                Notifier.shared.notify(
                    .connected,
                    title: t.notifConnectedTitle,
                    body: connectionSummary(server)
                )
                return
            }

            await sendDown()
        }

        guard phase == .connecting else { return }
        phase = .off
        errorMessage = t.errNoHandshake
    }

    private func bringUp(config: String) async -> Bool {
        let dns = useVPNDNS
        let kill = killSwitch
        let bypass = splitTunnel ? tunnelFiles.activeNetworks() : []

        let outcome: Result<Void, Error> = await Task.detached(priority: .userInitiated) {
            do {
                let response = try HelperClient.send(
                    HelperRequest(cmd: .up, config: config, setDNS: dns, killSwitch: kill, bypass: bypass),
                    timeout: 40
                )
                guard response.ok else {
                    throw HelperClient.Unavailable(reason: response.error ?? "не удалось поднять туннель")
                }
                return .success(())
            } catch {
                return .failure(error)
            }
        }.value

        if case .failure(let error) = outcome {
            lastBringUpError = (error as? HelperClient.Unavailable) != nil
                ? error.localizedDescription
                : nil
            return false
        }
        lastBringUpError = nil
        return true
    }

    private func rememberedPort(for serverID: Int) -> Int? {
        let value = UserDefaults.standard.integer(forKey: "prosto.port.\(serverID)")
        return value > 0 ? value : nil
    }

    private func rememberPort(_ port: Int, for serverID: Int) {
        UserDefaults.standard.set(port, forKey: "prosto.port.\(serverID)")
    }

    private func connectionSummary(_ server: PanelServer) -> String {
        let name = server.name(lang: lang)
        if let city = server.city(lang: lang), !city.isEmpty, city != name {
            return "\(name) · \(city)"
        }
        return name
    }

    func disconnect() async {
        guard phase != .off, phase != .disconnecting else { return }
        phase = .disconnecting
        stopTimer()
        watchdog?.cancel(); watchdog = nil
        heartbeat?.cancel(); heartbeat = nil
        await sendDown()
        phase = .off
    }

    private func sendDown() async {
        _ = await Task.detached(priority: .userInitiated) {
            try? HelperClient.send(HelperRequest(cmd: .down), timeout: 15)
        }.value
    }

    private func waitForHandshake(seconds limit: Int) async -> Bool {
        let deadline = Date().addingTimeInterval(TimeInterval(limit))
        while Date() < deadline {
            if Task.isCancelled { return false }
            let status = await Task.detached(priority: .utility) {
                try? HelperClient.send(HelperRequest(cmd: .status), timeout: 5).status
            }.value
            if let status {
                if !status.up { return false }
                if status.lastHandshake > 0 { return true }
            }
            try? await Task.sleep(nanoseconds: 500_000_000)
        }
        return false
    }

    private func startWatchdog() {
        watchdog?.cancel()
        watchdog = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 3_000_000_000)
                guard let self else { return }
                let status = await Task.detached(priority: .utility) {
                    try? HelperClient.send(HelperRequest(cmd: .status), timeout: 5).status
                }.value
                guard self.phase == .on else { return }
                guard let status else { continue }
                if !status.up {
                    self.stopTimer()
                    self.heartbeat?.cancel()
                    self.heartbeat = nil

                    self.phase = .off
                    if await self.reconnectAfterDrop() { return }

                    self.errorMessage = self.t.errTunnelDropped

                    Notifier.shared.notify(
                        .dropped,
                        title: self.t.notifDroppedTitle,
                        body: self.t.notifDroppedBody
                    )
                    return
                }
            }
        }
    }

    private static let reconnectDelays: [UInt64] = [1, 3, 8, 15, 30]

    private func reconnectAfterDrop() async -> Bool {
        guard autoReconnect else { return false }
        for delay in Self.reconnectDelays {
            try? await Task.sleep(nanoseconds: delay * 1_000_000_000)

            guard phase == .off, !Task.isCancelled else { return true }
            await connect()
            if phase == .on { return true }
        }
        return false
    }

    private func startHeartbeat() {
        heartbeat?.cancel()
        guard let token else { return }
        heartbeat = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                _ = try? await self.panel.heartbeat(token: token)
                try? await Task.sleep(nanoseconds: 60_000_000_000)
            }
        }
    }

    private func startTimer(from date: Date) {
        connectedAt = date
        seconds = 0
        let timer = Timer(timeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, let anchor = self.connectedAt else { return }
                let elapsed = Int(Date().timeIntervalSince(anchor))
                if elapsed != self.seconds { self.seconds = elapsed }
            }
        }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    private func stopTimer() {
        timer?.invalidate()
        timer = nil
        connectedAt = nil
        seconds = 0
    }

    var formattedDuration: String {
        let h = seconds / 3600, m = (seconds % 3600) / 60, s = seconds % 60
        return h > 0
            ? String(format: "%d:%02d:%02d", h, m, s)
            : String(format: "%02d:%02d", m, s)
    }

    private func cache(servers list: [PanelServer]) {
        guard let data = try? JSONEncoder().encode(list) else { return }
        Keychain.set(String(data: data, encoding: .utf8), for: Keys.servers)
    }

    private func loadCachedServers() -> [PanelServer] {
        guard let text = Keychain.get(Keys.servers), let data = text.data(using: .utf8) else { return [] }
        return (try? JSONDecoder().decode([PanelServer].self, from: data)) ?? []
    }

    private func loadCachedAccount() -> PanelAccount? {
        guard let data = defaults.data(forKey: Keys.account) else {
            guard let login = defaults.string(forKey: Keys.account) else { return nil }
            return PanelAccount(login: login)
        }
        return try? JSONDecoder().decode(PanelAccount.self, from: data)
    }

    private func loadCachedSubscription() -> PanelSubscription? {
        guard let data = defaults.data(forKey: Keys.subscription) else { return nil }
        return try? JSONDecoder().decode(PanelSubscription.self, from: data)
    }

    private func refreshGeo(for server: PanelServer) {
        guard server.id == Self.accessKeyServerID, !server.host.isEmpty else { return }
        let host = server.host
        let language = lang
        Task { [weak self] in
            guard let url = URL(
                string: "http://ip-api.com/json/\(host)?fields=status,country,countryCode,city&lang=\(language)"
            ) else { return }
            guard let (data, _) = try? await URLSession.shared.data(from: url),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  json["status"] as? String == "success"
            else { return }

            await MainActor.run {
                guard let self, var updated = self.servers.first(where: { $0.id == Self.accessKeyServerID }),
                      updated.host == host
                else { return }
                updated.country = json["country"] as? String
                updated.country_en = json["country"] as? String
                updated.city = json["city"] as? String
                updated.city_en = json["city"] as? String
                updated.country_code = json["countryCode"] as? String
                self.servers = self.servers.map { $0.id == Self.accessKeyServerID ? updated : $0 }
                self.cache(servers: self.servers)
            }
        }
    }
}
