import Foundation

/// Запуск системных утилит. Пути абсолютные и захардкожены: хелпер работает
/// от root, и подхватить чужой `ifconfig` из PATH он не должен.
enum Shell {

    struct Failure: LocalizedError {
        let command: String
        let code: Int32
        let output: String

        var errorDescription: String? {
            let text = output.trimmingCharacters(in: .whitespacesAndNewlines)
            return "\(command) вернул \(code)" + (text.isEmpty ? "" : ": \(text)")
        }
    }

    static let ifconfig = "/sbin/ifconfig"
    static let route = "/sbin/route"
    static let networksetup = "/usr/sbin/networksetup"
    static let pfctl = "/sbin/pfctl"

    /// Выполняет команду и возвращает stdout+stderr. Бросает, если код возврата не 0.
    @discardableResult
    static func run(_ path: String, _ arguments: [String], timeout: TimeInterval = 20) throws -> String {
        let (code, output) = try execute(path, arguments, timeout: timeout)
        guard code == 0 else {
            throw Failure(command: ([path] + arguments).joined(separator: " "), code: code, output: output)
        }
        return output
    }

    /// То же, но без исключения: удобно там, где отказ ожидаем — например,
    /// удаление маршрута, которого уже нет.
    @discardableResult
    static func tryRun(_ path: String, _ arguments: [String]) -> String? {
        guard let (code, output) = try? execute(path, arguments, timeout: 20), code == 0 else { return nil }
        return output
    }

    private static func execute(
        _ path: String,
        _ arguments: [String],
        timeout: TimeInterval
    ) throws -> (Int32, String) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: path)
        process.arguments = arguments

        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        // Утилиты запускаются без унаследованного окружения приложения:
        // networksetup и route ничего оттуда не берут, а PATH или DYLD_*
        // из чужого процесса — лишний способ подсунуть свой код в root.
        process.environment = ["PATH": "/usr/sbin:/usr/bin:/sbin:/bin"]

        try process.run()

        // Читаем в отдельном потоке: у route и networksetup вывод короткий,
        // но упереться в буфер трубы и повиснуть насмерть всё равно нельзя.
        var data = Data()
        let lock = NSLock()
        let reader = Thread {
            let chunk = pipe.fileHandleForReading.readDataToEndOfFile()
            lock.lock()
            data = chunk
            lock.unlock()
        }
        reader.start()

        let deadline = Date().addingTimeInterval(timeout)
        while process.isRunning && Date() < deadline {
            usleep(20_000)
        }
        if process.isRunning {
            process.terminate()
            usleep(200_000)
            if process.isRunning { kill(process.processIdentifier, SIGKILL) }
        }
        process.waitUntilExit()

        while !reader.isFinished && Date() < deadline.addingTimeInterval(2) {
            usleep(10_000)
        }
        lock.lock()
        let output = String(data: data, encoding: .utf8) ?? ""
        lock.unlock()

        return (process.terminationStatus, output)
    }
}
