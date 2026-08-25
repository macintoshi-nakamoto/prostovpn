import Foundation
import UserNotifications

@MainActor
final class Notifier {
    static let shared = Notifier()

    var enabled: Bool {
        get { UserDefaults.standard.object(forKey: Keys.enabled) as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: Keys.enabled) }
    }

    private enum Keys {
        static let enabled = "prosto.notifications"
        static let askedPermission = "prosto.notificationsAsked"
    }

    enum Reason: String {
        case connected
        case dropped
        case failed
        case signedOut
        case trafficLow
        case expiresSoon
        case updateReady
    }

    private var lastShown: [Reason: Date] = [:]

    private let available: Bool = Bundle.main.bundleIdentifier != nil
        && Bundle.main.bundleURL.pathExtension == "app"

    private var center: UNUserNotificationCenter? {
        available ? UNUserNotificationCenter.current() : nil
    }

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

    func clear(_ reason: Reason) {
        center?.removeDeliveredNotifications(withIdentifiers: [reason.rawValue])
    }

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

    func attachDelegate() {
        center?.delegate = delegate
    }
}
