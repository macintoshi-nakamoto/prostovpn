import Foundation
import UserNotifications

/*
 Системные сообщения.

 На Android о состоянии VPN рассказывает постоянное уведомление в шторке:
 без него оболочки Huawei и Xiaomi выгружают процесс, а человек не видит,
 работает туннель или нет. На Mac процесс никто не убивает, поэтому
 постоянного уведомления здесь быть не должно — его роль играет иконка в
 строке меню. Уведомления остаются для того, что случилось без участия
 человека: соединение оборвалось, панель отвязала устройство, кончается
 трафик или подписка, вышло обязательное обновление.

 Отдельно — окно приложения бывает закрыто, и тогда сказать об обрыве
 больше нечем.
 */
@MainActor
final class Notifier {

    static let shared = Notifier()

    /// Человек может выключить уведомления внутри приложения, не трогая
    /// системные настройки: разрешение спрашивается один раз, а передумать
    /// проще всего там же, где включал.
    var enabled: Bool {
        get { UserDefaults.standard.object(forKey: Keys.enabled) as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: Keys.enabled) }
    }

    private enum Keys {
        static let enabled = "prosto.notifications"
        static let askedPermission = "prosto.notificationsAsked"
    }

    /// Повод, по которому приложение обращается к человеку.
    ///
    /// Идентификатор у каждого повода свой: новое сообщение о том же самом
    /// заменяет предыдущее, а не копится стопкой в центре уведомлений.
    enum Reason: String {
        case connected
        case dropped
        case failed
        case signedOut
        case trafficLow
        case expiresSoon
        case updateReady
    }

    /// Когда последний раз говорили об этом поводе — чтобы предупреждение о
    /// трафике не приходило каждую минуту вместе с опросом панели.
    private var lastShown: [Reason: Date] = [:]

    /// Уведомления недоступны, пока приложение запущено не как бандл: центр
    /// уведомлений в таком случае не просто молчит, а роняет процесс.
    private let available: Bool = Bundle.main.bundleIdentifier != nil
        && Bundle.main.bundleURL.pathExtension == "app"

    private var center: UNUserNotificationCenter? {
        available ? UNUserNotificationCenter.current() : nil
    }

    /// Спрашивает разрешение — один раз за установку.
    ///
    /// Не на старте приложения: системный запрос сразу после первого запуска
    /// человек закрывает не глядя. Зовём его перед первым подключением, когда
    /// уже понятно, о чём вообще будут сообщения.
    func requestPermissionIfNeeded() {
        guard let center else { return }
        let defaults = UserDefaults.standard
        guard !defaults.bool(forKey: Keys.askedPermission) else { return }
        defaults.set(true, forKey: Keys.askedPermission)
        center.requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    func notify(_ reason: Reason, title: String, body: String, throttle: TimeInterval = 0) {
        guard enabled, let center else { return }
        if throttle > 0, let last = lastShown[reason], Date().timeIntervalSince(last) < throttle {
            return
        }
        lastShown[reason] = Date()

        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = reason == .connected ? nil : .default

        center.add(
            UNNotificationRequest(identifier: reason.rawValue, content: content, trigger: nil)
        )
    }

    /// Снимает сообщение, которое перестало быть правдой: показанный обрыв
    /// связи после успешного переподключения только сбивает с толку.
    func clear(_ reason: Reason) {
        center?.removeDeliveredNotifications(withIdentifiers: [reason.rawValue])
    }

    /// Разрешает показывать баннер поверх активного приложения.
    ///
    /// Без делегата система прячет уведомления, пока приложение на переднем
    /// плане, — а обрыв туннеля важен именно в этот момент.
    final class Delegate: NSObject, UNUserNotificationCenterDelegate {
        func userNotificationCenter(
            _ center: UNUserNotificationCenter,
            willPresent notification: UNNotification,
            withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
        ) {
            completionHandler([.banner, .sound])
        }
    }

    let delegate = Delegate()

    /// Ставится один раз при старте приложения.
    func attachDelegate() {
        center?.delegate = delegate
    }
}
