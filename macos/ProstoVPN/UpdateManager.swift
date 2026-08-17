import Foundation
import CryptoKit
import AppKit

/*
 Обновление приложения через панель — маковский родственник UpdateManager из
 Android и PanelUpdate из Windows-клиента.

 Общее с ними: панель отвечает на /api/v1/version, скачанное сверяется с
 обещанными sha256 и размером, состояние живёт вне экрана настроек —
 обязательное обновление показывается баннером на главном. Разная только
 установка: здесь приезжает DMG, его нужно смонтировать и подменить сам
 бандл приложения, из которого мы в этот момент работаем.

 Подменяет не приложение, а короткий скрипт: заменить .app, пока он
 выполняется, нельзя — сначала процесс должен закончиться.
 */
@MainActor
final class UpdateManager: ObservableObject {

    enum Stage: Equatable {
        /// Запрос к панели в полёте.
        case checking
        /// Новее ничего нет.
        case upToDate
        /// Есть версия новее — можно скачивать.
        case available
        /// Качаем образ, проценты — в значении.
        case downloading(Int)
        /// Скачанное сверяется и уезжает в установку.
        case installing
        /// Проверка или скачивание не удались — можно повторить.
        case failed(String)
    }

    @Published private(set) var stage: Stage = .checking
    /// Ответ панели; nil — новой версии нет или проверка не удалась.
    @Published private(set) var info: PanelUpdate?

    /// Обновление обязательное — баннер выходит и на главный экран.
    var mandatory: Bool { info?.mandatory == true }

    private let panel: PanelClient
    private var job: Task<Void, Never>?

    init(panel: PanelClient) {
        self.panel = panel
    }

    // MARK: - Проверка

    /// Спрашивает панель о новой версии.
    ///
    /// [silent] — для повторов при открытии настроек: тихая проверка не
    /// мигает «Проверяем…» поверх уже показанного результата и не затирает
    /// его разовой сетевой неудачей.
    func check(silent: Bool = false) {
        switch stage {
        case .downloading, .installing: return
        case .checking where silent: return
        default: break
        }

        job?.cancel()
        if !silent { stage = .checking }
        job = Task { [weak self] in
            guard let self else { return }
            do {
                let fresh = try await panel.checkUpdate(current: AppInfo.version)
                guard !Task.isCancelled else { return }
                info = fresh.update_available ? fresh : nil
                stage = info == nil ? .upToDate : .available
                if let info, info.mandatory {
                    Notifier.shared.notify(
                        .updateReady,
                        title: "Prosto VPN",
                        body: L10n.of(language).updateMandatoryNotice(info.version ?? ""),
                        throttle: 12 * 3600
                    )
                }
            } catch {
                guard !Task.isCancelled else { return }
                // Тихую неудачу не показываем: связь могла моргнуть на одну
                // проверку, а прежний результат ещё верен.
                if !silent { stage = .failed(error.localizedDescription) }
            }
        }
    }

    /// Язык для текста уведомления. Настройки живут в AppState, но тянуть
    /// его сюда ради одной строки — лишняя связь.
    private var language: String {
        UserDefaults.standard.string(forKey: "prosto.lang") ?? "ru"
    }

    // MARK: - Установка

    func install() {
        guard let info, let address = info.url else { return }
        switch stage {
        case .downloading, .installing: return
        default: break
        }

        // Адрес в панели никак не проверяется и допускает http://, а по
        // ссылке приедет исполняемый пакет — без TLS его не берём.
        guard let url = URL(string: address), url.scheme?.lowercased() == "https" else {
            stage = .failed(L10n.of(language).updateFailed)
            return
        }

        job?.cancel()
        stage = .downloading(0)
        job = Task { [weak self] in
            guard let self else { return }
            do {
                let image = try await download(url, expected: info)
                guard !Task.isCancelled else { return }
                stage = .installing
                try applyImage(at: image, version: info.version ?? "")
            } catch is CancellationError {
                stage = .available
            } catch {
                stage = .failed(error.localizedDescription)
            }
        }
    }

    /// Кнопка в состоянии «ошибка»: заново с того места, где сломалось.
    func retry() {
        if info != nil { install() } else { check() }
    }

    // MARK: - Скачивание и проверка

    struct Failure: LocalizedError {
        let reason: String
        var errorDescription: String? { reason }
    }

    private func download(_ url: URL, expected: PanelUpdate) async throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("ProstoVPNUpdate", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let version = (expected.version ?? "new").replacingOccurrences(
            of: "[^0-9A-Za-z._-]",
            with: "_",
            options: .regularExpression
        )
        let target = directory.appendingPathComponent("ProstoVPN-\(version).dmg")
        try? FileManager.default.removeItem(at: target)

        let downloader = FileDownloader()
        try await downloader.download(from: url, to: target) { [weak self] fraction in
            Task { @MainActor [weak self] in
                guard let self, case .downloading = self.stage else { return }
                self.stage = .downloading(Int(fraction * 100))
            }
        }

        // Размер и хеш — с тем, что обещала панель, а не с заголовками
        // ответа: заголовки подконтрольны тому же, кто подменил бы тело.
        let size = (try? FileManager.default.attributesOfItem(atPath: target.path)[.size] as? Int64) ?? 0
        if let promised = expected.size_bytes, promised > 0, promised != size {
            try? FileManager.default.removeItem(at: target)
            throw Failure(reason: L10n.of(language).updateBadFile)
        }
        if let promised = expected.sha256?.lowercased(), !promised.isEmpty {
            guard try sha256(of: target) == promised else {
                try? FileManager.default.removeItem(at: target)
                throw Failure(reason: L10n.of(language).updateBadFile)
            }
        }
        return target
    }

    private func sha256(of file: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        var digest = SHA256()
        while let chunk = try handle.read(upToCount: 1 << 20), !chunk.isEmpty {
            digest.update(data: chunk)
        }
        return digest.finalize().map { String(format: "%02x", $0) }.joined()
    }

    // MARK: - Подмена приложения

    /// Монтирует образ и заменяет собой установленное приложение.
    ///
    /// Заменить .app, пока он выполняется, нельзя — поэтому работу доделывает
    /// маленький скрипт: он дожидается выхода процесса, копирует новую
    /// версию на место старой и запускает её. Приложение при этом закрывается
    /// само, но туннель остаётся поднятым: его держит служба, а не окно.
    private func applyImage(at image: URL, version: String) throws {
        let mountPoint = try attach(image)
        guard let app = newestApp(in: mountPoint) else {
            detach(mountPoint)
            throw Failure(reason: L10n.of(language).updateBadFile)
        }

        let destination = Bundle.main.bundleURL
        let parent = destination.deletingLastPathComponent()
        guard FileManager.default.isWritableFile(atPath: parent.path) else {
            // Приложение лежит там, куда пользователю писать нельзя, —
            // например, его поставил другой человек. Молча ничего не делаем:
            // открываем образ, дальше перетаскиванием.
            NSWorkspace.shared.open(mountPoint)
            stage = .available
            return
        }

        let script = try writeInstallScript(
            source: app,
            destination: destination,
            mountPoint: mountPoint
        )

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = [script.path, String(ProcessInfo.processInfo.processIdentifier)]
        try process.run()

        // Дальше нас уже не будет: скрипт ждёт выхода этого процесса.
        NSApp.terminate(nil)
    }

    private func attach(_ image: URL) throws -> URL {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/hdiutil")
        process.arguments = ["attach", image.path, "-nobrowse", "-noverify", "-plist"]
        let output = Pipe()
        process.standardOutput = output
        process.standardError = Pipe()
        try process.run()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()

        guard process.terminationStatus == 0,
              let plist = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
              let entities = plist["system-entities"] as? [[String: Any]],
              let mount = entities.compactMap({ $0["mount-point"] as? String }).first
        else {
            throw Failure(reason: L10n.of(language).updateBadFile)
        }
        return URL(fileURLWithPath: mount)
    }

    private func detach(_ mountPoint: URL) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/hdiutil")
        process.arguments = ["detach", mountPoint.path, "-quiet"]
        try? process.run()
        process.waitUntilExit()
    }

    private func newestApp(in mountPoint: URL) -> URL? {
        let items = (try? FileManager.default.contentsOfDirectory(
            at: mountPoint,
            includingPropertiesForKeys: nil
        )) ?? []
        return items.first { $0.pathExtension == "app" }
    }

    /// Скрипт замены. Пишется в свой каталог во временной папке, чтобы после
    /// перезапуска ничего от него не осталось.
    private func writeInstallScript(source: URL, destination: URL, mountPoint: URL) throws -> URL {
        let script = """
        #!/bin/bash
        # Ставит обновление Prosto VPN после выхода приложения.
        set -u
        pid="$1"
        src=\(shellQuoted(source.path))
        dst=\(shellQuoted(destination.path))
        mount=\(shellQuoted(mountPoint.path))
        backup="$dst.old"

        # Ждём, пока приложение действительно закроется: подменять живой .app
        # нельзя, а «закрывается» на маке занимает доли секунды.
        for _ in $(seq 1 150); do
            /bin/kill -0 "$pid" 2>/dev/null || break
            /bin/sleep 0.2
        done

        /bin/rm -rf "$backup"
        if [ -d "$dst" ]; then
            /bin/mv "$dst" "$backup" || exit 1
        fi
        if ! /usr/bin/ditto "$src" "$dst"; then
            # Не получилось — возвращаем прежнюю версию, а не оставляем
            # человека вовсе без приложения.
            [ -d "$backup" ] && /bin/mv "$backup" "$dst"
            /usr/bin/hdiutil detach "$mount" -quiet 2>/dev/null
            exit 1
        fi
        /bin/rm -rf "$backup"
        /usr/bin/xattr -dr com.apple.quarantine "$dst" 2>/dev/null
        /usr/bin/hdiutil detach "$mount" -quiet 2>/dev/null
        /usr/bin/open "$dst"
        """

        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("ProstoVPNUpdate", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let url = directory.appendingPathComponent("install.sh")
        try script.write(to: url, atomically: true, encoding: .utf8)
        return url
    }

    private func shellQuoted(_ value: String) -> String {
        "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }
}

/// Скачивание файла с прогрессом.
///
/// Отдельным классом с делегатом, а не `URLSession.bytes`: побайтовый цикл на
/// двадцати мегабайтах образа тратит больше времени, чем сама загрузка.
private final class FileDownloader: NSObject, URLSessionDownloadDelegate, @unchecked Sendable {

    private var continuation: CheckedContinuation<Void, Error>?
    private var destination: URL?
    private var onProgress: ((Double) -> Void)?

    func download(from url: URL, to target: URL, progress: @escaping (Double) -> Void) async throws {
        destination = target
        onProgress = progress

        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 60
        let session = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }

        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            self.continuation = continuation
            session.downloadTask(with: url).resume()
        }
    }

    func urlSession(
        _ session: URLSession,
        downloadTask: URLSessionDownloadTask,
        didWriteData bytesWritten: Int64,
        totalBytesWritten: Int64,
        totalBytesExpectedToWrite: Int64
    ) {
        guard totalBytesExpectedToWrite > 0 else { return }
        onProgress?(Double(totalBytesWritten) / Double(totalBytesExpectedToWrite))
    }

    func urlSession(
        _ session: URLSession,
        downloadTask: URLSessionDownloadTask,
        didFinishDownloadingTo location: URL
    ) {
        // Временный файл живёт ровно до возврата из этого метода.
        guard let destination else { return }
        do {
            try? FileManager.default.removeItem(at: destination)
            try FileManager.default.moveItem(at: location, to: destination)
        } catch {
            continuation?.resume(throwing: error)
            continuation = nil
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let continuation else { return }
        self.continuation = nil
        if let error {
            continuation.resume(throwing: error)
        } else if let code = (task.response as? HTTPURLResponse)?.statusCode, !(200..<300).contains(code) {
            continuation.resume(throwing: URLError(.badServerResponse))
        } else {
            continuation.resume()
        }
    }
}
