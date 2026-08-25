import Foundation
import Security

enum Keychain {
    static var accessGroup: String? {
        Bundle.main.object(forInfoDictionaryKey: "KeychainAccessGroup") as? String
    }

    enum Key: String {
        case panelToken = "prosto.token"

        case tunnelConfig = "prosto.tunnelConfig"

        case deviceId = "prosto.deviceId"
    }

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

    static func removeAll() {
        remove(.panelToken)
        remove(.tunnelConfig)
    }

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
