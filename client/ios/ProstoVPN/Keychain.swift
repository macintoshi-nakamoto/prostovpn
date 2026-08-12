import Foundation
import Security

/// Хранилище секретов: токен сессии и конфиги туннеля.
///
/// Не UserDefaults, и это не перестраховка. UserDefaults — это plist в
/// песочнице приложения: он попадает в резервную копию iTunes/iCloud, в
/// нешифрованном бэкапе читается открытым текстом, а на устройстве с
/// джейлбрейком доступен любому процессу. Токен сессии — это доступ к
/// учётной записи, конфиг туннеля — приватный ключ WireGuard.
///
/// `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` выбран намеренно:
/// расширение туннеля стартует в фоне (по Always-on, после перезагрузки) и
/// обязано прочитать конфиг без разблокировки экрана — `WhenUnlocked` там
/// не сработает. `ThisDeviceOnly` не даёт секретам уехать в резервную копию
/// и оттуда на чужое устройство.
enum Keychain {

    /// Группа доступа: приложение и расширение туннеля — разные процессы,
    /// и общий доступ к связке ключей у них появляется только через
    /// App Group / Keychain Sharing. Значение подставляется сборкой.
    static var accessGroup: String? {
        Bundle.main.object(forInfoDictionaryKey: "KeychainAccessGroup") as? String
    }

    enum Key: String {
        /// Токен сессии в панели.
        case panelToken = "prosto.token"
        /// Конфиг активного сервера — его читает расширение туннеля.
        case tunnelConfig = "prosto.tunnelConfig"
        /// Постоянный идентификатор установки: по нему панель считает
        /// переустановку тем же устройством, а не вторым.
        case deviceId = "prosto.deviceId"
    }

    // MARK: - Чтение и запись

    static func string(_ key: Key) -> String? {
        guard let data = data(key) else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func set(_ value: String?, for key: Key) {
        guard let value, !value.isEmpty else {
            remove(key)
            return
        }
        set(Data(value.utf8), for: key)
    }

    static func data(_ key: Key) -> Data? {
        var query = baseQuery(key)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess else { return nil }
        return item as? Data
    }

    static func set(_ data: Data, for key: Key) {
        let query = baseQuery(key)
        let attributes: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]

        // Обновляем существующую запись, а не удаляем и создаём заново:
        // между удалением и вставкой расширение туннеля могло бы прочитать
        // пустоту и уронить подключение на ровном месте.
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var insert = query
            insert.merge(attributes) { current, _ in current }
            SecItemAdd(insert as CFDictionary, nil)
        }
    }

    static func remove(_ key: Key) {
        SecItemDelete(baseQuery(key) as CFDictionary)
    }

    /// Чистит всё при выходе: чужой токен на устройстве не нужен никому.
    static func removeAll() {
        remove(.panelToken)
        remove(.tunnelConfig)
        // deviceId переживает выход намеренно: это идентификатор установки,
        // а не человека. Иначе повторный вход считался бы новым устройством
        // и съедал ещё одно место по лимиту тарифа.
    }

    /// Идентификатор установки: заводится один раз и живёт до удаления
    /// приложения.
    static func deviceId() -> String {
        if let existing = string(.deviceId), !existing.isEmpty { return existing }
        let fresh = UUID().uuidString
        set(fresh, for: .deviceId)
        return fresh
    }

    private static func baseQuery(_ key: Key) -> [String: Any] {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "cc.prostovpn.app",
            kSecAttrAccount as String: key.rawValue,
        ]
        if let accessGroup {
            query[kSecAttrAccessGroup as String] = accessGroup
        }
        return query
    }
}
