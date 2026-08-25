import Foundation

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

    @discardableResult
    static func run(_ path: String, _ arguments: [String], timeout: TimeInterval = 20) throws -> String {
        let (code, output) = try execute(path, arguments, timeout: timeout)
        guard code == 0 else {
            throw Failure(command: ([path] + arguments).joined(separator: " "), code: code, output: output)
        }
        return output
    }

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

        process.environment = ["PATH": "/usr/sbin:/usr/bin:/sbin:/bin"]

        try process.run()

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
