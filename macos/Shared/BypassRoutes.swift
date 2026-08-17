import Foundation

/*
 Сети, которые должны ходить мимо туннеля.

 Госуслуги, ЕСИА и порталы Московской области отвечают только с российских
 адресов: из-за границы вход в ЕСИА не проходит, а школьные сервисы просто
 не открываются. Поэтому трафик к ним идёт напрямую, со своего адреса, —
 остальное остаётся в VPN.

 Списком сетей, а не отдельными адресами: у CDN Госуслуг адреса
 ротируются, и привязка к конкретному IP отвалилась бы через день.
 */

public struct BypassNetwork: Sendable {
    public let cidr: String
    /// Что за сервис — чтобы список можно было читать и править.
    public let comment: String

    public init(_ cidr: String, _ comment: String) {
        self.cidr = cidr
        self.comment = comment
    }
}

public enum BypassRoutes {

    /// Российские государственные и образовательные сервисы.
    public static let russianServices: [BypassNetwork] = [
        BypassNetwork("51.250.54.0/23", "Yandex Cloud — edumsko.ru, сайты школ Московской области"),
        BypassNetwork("82.202.190.0/24", "uslugi.mosreg.ru и Школьный портал school.mosreg.ru"),
        BypassNetwork("185.169.155.0/24", "mosreg.ru"),
        BypassNetwork("213.59.252.0/22", "gosuslugi.ru: сайт, esia (вход) и личный кабинет"),
        BypassNetwork("109.207.0.0/20", "Электронное правительство — pos.gosuslugi.ru и смежные"),
        BypassNetwork("212.193.152.0/22", "gu-st.ru — статика Госуслуг"),
        BypassNetwork("46.235.184.0/22", "gu-st.ru — статика Госуслуг, второй диапазон"),
    ]

    public static var russianServiceCIDRs: [String] {
        russianServices.map(\.cidr)
    }

    /// Проверка перед тем, как отдавать сеть в `route`.
    ///
    /// Хелпер работает от root, и подсунуть ему в аргумент что попало быть
    /// не должно — принимаем только «адрес/длина префикса».
    public static func isValidCIDR(_ value: String) -> Bool {
        let parts = value.components(separatedBy: "/")
        guard parts.count == 2, let prefix = Int(parts[1]) else { return false }

        var v4 = in_addr()
        if inet_pton(AF_INET, parts[0], &v4) == 1 {
            return (0...32).contains(prefix)
        }
        var v6 = in6_addr()
        if inet_pton(AF_INET6, parts[0], &v6) == 1 {
            return (0...128).contains(prefix)
        }
        return false
    }
}
