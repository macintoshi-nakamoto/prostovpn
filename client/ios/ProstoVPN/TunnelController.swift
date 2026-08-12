import Foundation
import NetworkExtension

/// Управление системным VPN-профилем.
///
/// На iOS туннель поднимает не приложение, а системное расширение
/// (`ProstoVPNTunnel`): свой процесс, свои права, своя жизнь. Приложение
/// только заводит профиль в настройках устройства и просит расширение
/// стартовать. Отсюда два следствия, которых нет на Android:
///
/// * туннель переживает выгрузку приложения — процесс расширения системный,
///   и «свернул приложение — оборвался VPN» тут невозможно;
/// * состояние подключения приходит уведомлением от системы, а не считается
///   приложением, поэтому экран не может разойтись с действительностью.
@MainActor
final class TunnelController: ObservableObject {

    /// Что сейчас с туннелем — ровно то, что говорит система.
    enum Status: Equatable {
        case off
        case connecting
        case on
        case disconnecting
        /// Профиль не заведён: человек ещё не разрешал VPN на устройстве.
        case notConfigured
    }

    @Published private(set) var status: Status = .notConfigured
    /// Когда подключились — по нему считается таймер на экране. Время берём
    /// у системы, а не у своего счётчика: свой уходил бы вперёд при
    /// переподключении в фоне.
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

    // MARK: - Профиль

    /// Загружает профиль из настроек устройства. Нет профиля — статус
    /// `.notConfigured`, и первое подключение попросит разрешение.
    func load() async {
        do {
            let managers = try await NETunnelProviderManager.loadAllFromPreferences()
            manager = managers.first
            readStatus()
        } catch {
            lastError = error.localizedDescription
        }
    }

    /// Заводит или обновляет профиль под выбранный сервер.
    ///
    /// Конфиг в профиль НЕ кладём. `providerConfiguration` лежит в системных
    /// настройках открытым текстом и виден в резервной копии; там был бы
    /// приватный ключ WireGuard. Вместо этого конфиг лежит в связке ключей,
    /// а расширение читает его оттуда само — см. Keychain.
    private func saveProfile(serverName: String) async throws -> NETunnelProviderManager {
        let manager = self.manager ?? NETunnelProviderManager()

        let proto = (manager.protocolConfiguration as? NETunnelProviderProtocol) ?? NETunnelProviderProtocol()
        // Адрес узла система показывает в настройках VPN — пишем страну, а
        // не хост: человеку понятнее, а адрес узла наружу не выносим.
        proto.serverAddress = serverName
        proto.providerBundleIdentifier = Self.tunnelBundleId
        manager.protocolConfiguration = proto

        manager.localizedDescription = "Prosto VPN"
        manager.isEnabled = true

        /*
        Подключение по требованию выключено намеренно.

        onDemand поднимает туннель на любую сетевую активность, в том числе
        когда человек его выключил, — и выглядит это как «VPN включается
        сам, я его не просил». Кнопка на экране должна значить ровно то, что
        написано.
        */
        manager.isOnDemandEnabled = false

        try await manager.saveToPreferences()
        // Перечитываем: после сохранения система возвращает свой экземпляр,
        // и старый становится несвежим — connection у него не работает.
        try await manager.loadFromPreferences()
        self.manager = manager
        return manager
    }

    // MARK: - Подключение

    /// Поднимает туннель с этим конфигом.
    ///
    /// Конфиг кладём в связку ключей ДО старта: расширение читает его
    /// оттуда первым делом, и порядок здесь обязателен.
    func connect(config: String, serverName: String) async {
        lastError = nil
        Keychain.set(config, for: .tunnelConfig)

        do {
            let manager = try await saveProfile(serverName: serverName)
            // Пустые options — расширение берёт всё из связки ключей.
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

    /// Смена страны на лету: система сама снимет прежний туннель и поднимет
    /// новый, отдельного «отключить, подождать, подключить» не нужно.
    func reconnect(config: String, serverName: String) async {
        if status == .on || status == .connecting {
            disconnect()
            // Ждём фактического снятия: старт поверх живого туннеля система
            // отвергает, и подключение молча не происходит.
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

    // MARK: - Состояние

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

    /// Идентификатор расширения. Держим рядом с профилем: разойдись он с
    /// тем, что в проекте, — система молча не найдёт расширение, и туннель
    /// не поднимется без единой ошибки на экране.
    static var tunnelBundleId: String {
        (Bundle.main.object(forInfoDictionaryKey: "TunnelBundleIdentifier") as? String)
            ?? ((Bundle.main.bundleIdentifier ?? "cc.prostovpn.app") + ".tunnel")
    }

    private static func readable(_ error: Error) -> String {
        let ns = error as NSError
        // Отказ в разрешении на VPN — единственная ошибка, которую человек
        // может исправить сам, поэтому её называем отдельно.
        if ns.domain == NEVPNErrorDomain, ns.code == NEVPNError.configurationReadWriteFailed.rawValue {
            return "permissionDenied"
        }
        return ns.localizedDescription
    }
}
