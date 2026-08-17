import Foundation
import IOKit

/// Кто мы для панели: постоянный идентификатор установки и понятное имя.
///
/// Пир WireGuard принадлежит устройству, а не учётной записи, и лимит
/// устройств в тарифе считается по `device_id`. Без него панель принимает
/// каждый вход за «ключ учётки»: этот Mac и чужой телефон становятся одним и
/// тем же устройством, а отключить его из кабинета по отдельности нельзя.
enum DeviceIdentity {

    private static let keychainAccount = "prosto.installId"

    /// Постоянный идентификатор установки.
    ///
    /// В связке ключей, а не в UserDefaults: переустановка приложения не
    /// должна съедать ещё один слот тарифа. Случайный UUID, а не серийный
    /// номер машины — панели незачем знать железо.
    static var installID: String {
        if let saved = Keychain.get(keychainAccount), !saved.isEmpty { return saved }
        let fresh = UUID().uuidString
        Keychain.set(fresh, for: keychainAccount)
        return fresh
    }

    /// «MacBook Pro Ивана» в списке устройств понятнее, чем пустая строка.
    static var name: String {
        let host = Host.current().localizedName?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !host.isEmpty { return host }
        return model.isEmpty ? "Mac" : model
    }

    /// Модельный идентификатор вида «Mac15,3» — запасной вариант имени.
    static var model: String {
        var size = 0
        sysctlbyname("hw.model", nil, &size, nil, 0)
        guard size > 0 else { return "" }
        var bytes = [CChar](repeating: 0, count: size)
        sysctlbyname("hw.model", &bytes, &size, nil, 0)
        return String(cString: bytes)
    }
}
