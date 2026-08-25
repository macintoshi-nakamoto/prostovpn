import Foundation
import IOKit

enum DeviceIdentity {
    private static let keychainAccount = "prosto.installId"

    static var installID: String {
        if let saved = Keychain.get(keychainAccount), !saved.isEmpty { return saved }
        let fresh = UUID().uuidString
        Keychain.set(fresh, for: keychainAccount)
        return fresh
    }

    static var name: String {
        let host = Host.current().localizedName?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !host.isEmpty { return host }
        return model.isEmpty ? "Mac" : model
    }

    static var model: String {
        var size = 0
        sysctlbyname("hw.model", nil, &size, nil, 0)
        guard size > 0 else { return "" }
        var bytes = [CChar](repeating: 0, count: size)
        sysctlbyname("hw.model", &bytes, &size, nil, 0)
        return String(cString: bytes)
    }
}
