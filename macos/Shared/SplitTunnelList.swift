import Foundation

/*
 Разбор списков раздельного туннелирования.

 Формат тот же, что у Android (`android/app/src/main/assets/ru-split-tunnel.json`),
 чтобы один и тот же файл работал на всех платформах:

     [{"hostname": "2.56.24.0/22", "ip": ""}, ...]

 Принимаются также простой массив строк, объект со списком внутри и
 текстовый файл по одной сети на строку — люди приносят списки в том виде,
 в каком нашли.
 */

public enum SplitTunnelList {

    /// Сети из файла. Мусор пропускается молча: один битый адрес не повод
    /// выбрасывать список целиком.
    public static func parse(_ data: Data) -> [String] {
        if let object = try? JSONSerialization.jsonObject(with: data) {
            var found: [String] = []
            collect(object, into: &found)
            if !found.isEmpty { return unique(found) }
        }

        guard let text = String(data: data, encoding: .utf8) else { return [] }
        return unique(
            text.components(separatedBy: .newlines)
                .map { $0.components(separatedBy: "#")[0].trimmingCharacters(in: .whitespaces) }
                .filter { isNetwork($0) }
        )
    }

    public static func parse(contentsOf url: URL) -> [String] {
        guard let data = try? Data(contentsOf: url) else { return [] }
        return parse(data)
    }

    private static func collect(_ object: Any, into result: inout [String]) {
        if let text = object as? String {
            if isNetwork(text) { result.append(text) }
        } else if let array = object as? [Any] {
            for item in array { collect(item, into: &result) }
        } else if let dictionary = object as? [String: Any] {
            // У формата Android сеть лежит в hostname, а поле ip пустое.
            for key in ["hostname", "ip", "cidr", "subnet", "network"] {
                if let text = dictionary[key] as? String, isNetwork(text) {
                    result.append(text)
                    return
                }
            }
            for value in dictionary.values { collect(value, into: &result) }
        }
    }

    private static func unique(_ items: [String]) -> [String] {
        var seen = Set<String>()
        return items.filter { seen.insert($0).inserted }
    }

    /// Адрес или сеть IPv4/IPv6. Доменные имена не берём: маршрут строится
    /// по адресу, а имя пришлось бы резолвить — и получать разный ответ
    /// каждый раз.
    public static func isNetwork(_ value: String) -> Bool {
        guard !value.isEmpty else { return false }
        let parts = value.components(separatedBy: "/")
        guard parts.count <= 2 else { return false }
        if parts.count == 2, Int(parts[1]) == nil { return false }

        var v4 = in_addr()
        if inet_pton(AF_INET, parts[0], &v4) == 1 {
            return parts.count == 1 || (0...32).contains(Int(parts[1]) ?? -1)
        }
        var v6 = in6_addr()
        if inet_pton(AF_INET6, parts[0], &v6) == 1 {
            return parts.count == 1 || (0...128).contains(Int(parts[1]) ?? -1)
        }
        return false
    }
}
