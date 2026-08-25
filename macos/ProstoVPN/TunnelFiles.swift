import Foundation
import Combine

struct TunnelFile: Codable, Identifiable, Equatable {
    var id: String
    var name: String

    var count: Int
    var isDefault: Bool

    static let defaultID = "default"
}

@MainActor
final class TunnelFiles: ObservableObject {
    @Published private(set) var files: [TunnelFile] = []
    @Published var activeID: String {
        didSet { defaults.set(activeID, forKey: Keys.active) }
    }

    private let defaults = UserDefaults.standard

    private enum Keys {
        static let files = "prosto.tunnelFiles"
        static let active = "prosto.tunnelActive"
    }

    static let defaultFileName = "ru-split-tunnel.json"

    init() {
        activeID = defaults.string(forKey: Keys.active) ?? TunnelFile.defaultID
        reload()
    }

    func reload() {
        var stored: [TunnelFile] = []
        if let data = defaults.data(forKey: Keys.files),
           let saved = try? JSONDecoder().decode([TunnelFile].self, from: data) {
            stored = saved.filter { FileManager.default.fileExists(atPath: url(for: $0).path) }
        }
        files = [builtIn] + stored
        if !files.contains(where: { $0.id == activeID }) {
            activeID = TunnelFile.defaultID
        }
        persist()
    }

    private var builtIn: TunnelFile {
        TunnelFile(
            id: TunnelFile.defaultID,
            name: Self.defaultFileName,
            count: Self.builtInNetworks.count,
            isDefault: true
        )
    }

    var active: TunnelFile? {
        files.first { $0.id == activeID }
    }

    func activeNetworks() -> [String] {
        let fromFile: [String]
        if activeID == TunnelFile.defaultID {
            fromFile = Self.builtInNetworks
        } else if let file = active {
            fromFile = SplitTunnelList.parse(contentsOf: url(for: file))
        } else {
            fromFile = Self.builtInNetworks
        }

        var seen = Set(fromFile)
        return fromFile + BypassRoutes.russianServiceCIDRs.filter { seen.insert($0).inserted }
    }

    static let builtInNetworks: [String] = {
        guard let path = Bundle.main.path(forResource: defaultFileName, ofType: nil) else { return [] }
        return SplitTunnelList.parse(contentsOf: URL(fileURLWithPath: path))
    }()

    enum ImportError: LocalizedError {
        case unreadable
        case empty

        var errorDescription: String? {
            switch self {
            case .unreadable: return "не удалось прочитать файл"
            case .empty: return "в файле нет ни одной сети"
            }
        }
    }

    @discardableResult
    func add(from source: URL) throws -> TunnelFile {
        guard let data = try? Data(contentsOf: source) else { throw ImportError.unreadable }
        let networks = SplitTunnelList.parse(data)
        guard !networks.isEmpty else { throw ImportError.empty }

        let directory = try storageDirectory()
        var name = source.lastPathComponent
        var attempt = 1
        while files.contains(where: { $0.name == name }) {
            let base = source.deletingPathExtension().lastPathComponent
            let ext = source.pathExtension.isEmpty ? "" : ".\(source.pathExtension)"
            name = "\(base)_\(attempt)\(ext)"
            attempt += 1
        }

        try data.write(to: directory.appendingPathComponent(name), options: .atomic)

        let file = TunnelFile(id: UUID().uuidString, name: name, count: networks.count, isDefault: false)
        files.append(file)
        activeID = file.id
        persist()
        return file
    }

    func remove(_ file: TunnelFile) {
        guard !file.isDefault else { return }
        try? FileManager.default.removeItem(at: url(for: file))
        files.removeAll { $0.id == file.id }
        if activeID == file.id { activeID = TunnelFile.defaultID }
        persist()
    }

    private func url(for file: TunnelFile) -> URL {
        (try? storageDirectory())?.appendingPathComponent(file.name)
            ?? URL(fileURLWithPath: "/dev/null")
    }

    private func storageDirectory() throws -> URL {
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let directory = support.appendingPathComponent("ProstoVPN/Tunneling", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    private func persist() {
        let custom = files.filter { !$0.isDefault }
        if let data = try? JSONEncoder().encode(custom) {
            defaults.set(data, forKey: Keys.files)
        }
    }
}
