import Foundation

/// Перебор точек подключения одного узла.
///
/// Зачем это нужно. Узел слушает несколько портов, и какой из них пройдёт —
/// зависит не от нас, а от сети человека: канонический 51820 у заметной части
/// операторов режут как известный порт WireGuard. Снаружи это выглядит как
/// исправное приложение, исправный сервер и вечное «подключение».
///
/// До сих пор этот клиент делал ровно одну попытку на одном порту и при
/// неудаче показывал ошибку. Теперь он перебирает кандидатов — и, что важнее,
/// **запоминает сработавшего**: у человека, в чьей сети проходит только 443,
/// каждое подключение не должно начинаться с полуминутной потери на 51820.
///
/// Порядок намеренно не «пробуем всё разом»: у WireGuard попытка означает
/// поднятый интерфейс и настроенные маршруты, и держать три таких сразу —
/// значит трижды переписать таблицу маршрутизации системы. Поэтому кандидаты
/// пробуются подряд, но с коротким бюджетом на каждого.
struct Candidate: Equatable, CustomStringConvertible {
    let host: String
    let port: Int

    var description: String { "\(host):\(port)" }
}

enum Candidates {

    /// Регулярное выражение строки `Endpoint = host:port` в wg-quick.
    ///
    /// Меняем ровно её и ровно хвост: в конфиге хватает других чисел после
    /// «=» и «:» — MTU, junk-параметры, адреса, — и любая менее строгая
    /// замена однажды испортит ключ вместо порта. Такая порча не видна
    /// глазом: конфиг остаётся верным, а туннель просто не поднимается.
    private static let endpointLine = try! NSRegularExpression(
        pattern: #"(?im)^([ \t]*Endpoint[ \t]*=[ \t]*)(\S+?)(?::(\d+))?[ \t]*$"#
    )

    /// Порт из конфига; `nil` — строки нет или порт не указан.
    static func port(in config: String) -> Int? {
        let range = NSRange(config.startIndex..., in: config)
        guard let match = endpointLine.firstMatch(in: config, range: range),
              match.numberOfRanges > 3,
              let portRange = Range(match.range(at: 3), in: config)
        else { return nil }
        return Int(config[portRange])
    }

    /// Хост из конфига; `nil` — строки нет.
    static func host(in config: String) -> String? {
        let range = NSRange(config.startIndex..., in: config)
        guard let match = endpointLine.firstMatch(in: config, range: range),
              let hostRange = Range(match.range(at: 2), in: config)
        else { return nil }
        return String(config[hostRange])
    }

    /// Тот же конфиг, но эндпоинт смотрит в другой порт.
    static func with(config: String, port: Int) -> String {
        let range = NSRange(config.startIndex..., in: config)
        return endpointLine.stringByReplacingMatches(
            in: config, range: range, withTemplate: "$1$2:\(port)"
        )
    }

    /// Порядок перебора: сначала запомненный, потом из конфига, потом запасные.
    ///
    /// Запомненный идёт первым не ради скорости, а ради предсказуемости.
    /// Дубликаты выбрасываем: список приходит от панели, и она намеренно
    /// кладёт туда основной порт — клиенту дешевле не сходить дважды в одно
    /// место, чем панели гадать, что у него в конфиге.
    static func order(config: String, remembered: Int?, alternatives: [Int]) -> [Candidate] {
        guard let host = host(in: config), !host.isEmpty else { return [] }
        var ports: [Int] = []
        if let remembered, remembered > 0 { ports.append(remembered) }
        if let configPort = port(in: config), configPort > 0, !ports.contains(configPort) {
            ports.append(configPort)
        }
        for port in alternatives where port > 0 && !ports.contains(port) {
            ports.append(port)
        }
        return ports.map { Candidate(host: host, port: $0) }
    }
}
