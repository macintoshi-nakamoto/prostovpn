import Foundation
import NetworkExtension

@MainActor
final class TunnelController: ObservableObject {
    enum Status: Equatable {
        case off
        case connecting
        case on
        case disconnecting

        case notConfigured
    }

    @Published private(set) var status: Status = .notConfigured

    @Published private(set) var connectedDate: Date?
    @Published private(set) var lastError: String?

    private var manager: NETunnelProviderManager?
    private var observer: NSObjectProtocol?

    init() {
        observer = NotificationCenter.default.addObserver(
            forName: .NEVPNStatusDidChange,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.readStatus() }
        }
    }

    deinit {
        if let observer { NotificationCenter.default.removeObserver(observer) }
    }

    func load() async {
        do {
            let managers = try await NETunnelProviderManager.loadAllFromPreferences()
            manager = managers.first
            readStatus()
        } catch {
            lastError = error.localizedDescription
        }
    }

    private func saveProfile(serverName: String) async throws -> NETunnelProviderManager {
        let manager = self.manager ?? NETunnelProviderManager()

        let proto = (manager.protocolConfiguration as? NETunnelProviderProtocol) ?? NETunnelProviderProtocol()

        proto.serverAddress = serverName
        proto.providerBundleIdentifier = Self.tunnelBundleId
        manager.protocolConfiguration = proto

        manager.localizedDescription = "Prosto VPN"
        manager.isEnabled = true

        manager.isOnDemandEnabled = false

        try await manager.saveToPreferences()

        try await manager.loadFromPreferences()
        self.manager = manager
        return manager
    }

    func connect(config: String, serverName: String) async {
        lastError = nil
        Keychain.set(config, for: .tunnelConfig)

        do {
            let manager = try await saveProfile(serverName: serverName)

            try manager.connection.startVPNTunnel(options: [:])
            status = .connecting
        } catch {
            status = .off
            lastError = Self.readable(error)
        }
    }

    func disconnect() {
        manager?.connection.stopVPNTunnel()
        status = .disconnecting
    }

    func reconnect(config: String, serverName: String) async {
        if status == .on || status == .connecting {
            disconnect()

            await waitFor(.off, timeout: 8)
        }
        await connect(config: config, serverName: serverName)
    }

    private func waitFor(_ target: Status, timeout: TimeInterval) async {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            readStatus()
            if status == target { return }
            try? await Task.sleep(nanoseconds: 150_000_000)
        }
    }

    private func readStatus() {
        guard let connection = manager?.connection else {
            status = .notConfigured
            connectedDate = nil
            return
        }
        switch connection.status {
        case .connected:
            status = .on
            connectedDate = connection.connectedDate
        case .connecting, .reasserting:
            status = .connecting
        case .disconnecting:
            status = .disconnecting
        case .disconnected, .invalid:
            status = .off
            connectedDate = nil
        @unknown default:
            status = .off
        }
    }

    static var tunnelBundleId: String {
        (Bundle.main.object(forInfoDictionaryKey: "TunnelBundleIdentifier") as? String)
            ?? ((Bundle.main.bundleIdentifier ?? "cc.prostovpn.app") + ".tunnel")
    }

    private static func readable(_ error: Error) -> String {
        let ns = error as NSError

        if ns.domain == NEVPNErrorDomain, ns.code == NEVPNError.configurationReadWriteFailed.rawValue {
            return "permissionDenied"
        }
        return ns.localizedDescription
    }
}
