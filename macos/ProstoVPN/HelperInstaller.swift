import Foundation

/// Установка службы подключения.
///
/// Поднять сетевой интерфейс и переписать таблицу маршрутов может только
/// root, а приложение работает от пользователя. Поэтому один раз мы просим
/// пароль администратора и ставим маленький демон, который делает эту
/// работу по команде.
enum HelperInstaller {

    struct Failure: LocalizedError {
        let reason: String
        var errorDescription: String? { reason }
    }

    /// Пользователь отказался вводить пароль — это не поломка, а решение.
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
            // -128 — стандартный код «пользователь нажал Отмена» в Apple Events.
            if message.contains("-128") || message.contains("User canceled") {
                throw Cancelled()
            }
            throw Failure(reason: message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                ? "не удалось установить службу подключения"
                : message.trimmingCharacters(in: .whitespacesAndNewlines))
        }

        // launchd поднимает демон асинхронно: сокет уже есть, а принимать
        // соединения он может начать на доли секунды позже. Проверяем
        // несколько раз, иначе успешная установка выглядит провальной.
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

    /// Ставит службу, если её ещё нет. Возвращает true, если всё готово.
    static func ensureInstalled() throws {
        if HelperClient.isReady() { return }
        try install()
    }

    // MARK: - Экранирование

    /// Аргумент для /bin/bash: одинарные кавычки, внутри них живёт что угодно.
    private static func quotedForShell(_ value: String) -> String {
        "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }

    /// Строковый литерал AppleScript. Пути к бандлу содержат пробелы и могут
    /// содержать кавычки, поэтому склеивать их руками нельзя.
    private static func appleScriptString(_ value: String) -> String {
        "\"" + value
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
            + "\""
    }
}
