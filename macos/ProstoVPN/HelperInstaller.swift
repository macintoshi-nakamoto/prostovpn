import Foundation

enum HelperInstaller {
    struct Failure: LocalizedError {
        let reason: String
        var errorDescription: String? { reason }
    }

    struct Cancelled: LocalizedError {
        var errorDescription: String? { "установка отменена" }
    }

    private static func resource(_ name: String) throws -> String {
        guard let path = Bundle.main.path(forResource: name, ofType: nil) else {
            throw Failure(reason: "в приложении не хватает файла \(name)")
        }
        return path
    }

    static func install() throws {
        let script = try resource("install-helper.sh")
        let helper = try resource("com.prostovpn.helper")
        let engine = try resource("prostovpn-awg")
        let plist = try resource("com.prostovpn.helper.plist")

        let command = [script, helper, engine, plist, String(getuid())]
            .map(quotedForShell)
            .joined(separator: " ")

        let appleScript = """
        do shell script \(appleScriptString("/bin/bash " + command)) with administrator privileges
        """

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", appleScript]
        let pipe = Pipe()
        process.standardError = pipe
        process.standardOutput = Pipe()

        try process.run()
        let errorData = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()

        guard process.terminationStatus == 0 else {
            let message = String(data: errorData, encoding: .utf8) ?? ""

            if message.contains("-128") || message.contains("User canceled") {
                throw Cancelled()
            }
            throw Failure(reason: message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                ? "не удалось установить службу подключения"
                : message.trimmingCharacters(in: .whitespacesAndNewlines))
        }

        let deadline = Date().addingTimeInterval(5)
        var lastVersion: String?
        while Date() < deadline {
            if let response = try? HelperClient.send(HelperRequest(cmd: .ping), timeout: 2), response.ok {
                if response.version == HelperPaths.version { return }
                lastVersion = response.version
            }
            Thread.sleep(forTimeInterval: 0.25)
        }

        if let lastVersion {
            throw Failure(reason: "отвечает служба версии \(lastVersion), а нужна \(HelperPaths.version)")
        }
        throw Failure(reason: "служба установлена, но не отвечает")
    }

    static func ensureInstalled() throws {
        if HelperClient.isReady() { return }
        try install()
    }

    private static func quotedForShell(_ value: String) -> String {
        "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }

    private static func appleScriptString(_ value: String) -> String {
        "\"" + value
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
            + "\""
    }
}
