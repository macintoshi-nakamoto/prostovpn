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

        // Дальше — сервисы, которые с зарубежного адреса просто не работают:
        // Ozon зацикливает редирект, Кинопоиск не поднимает сессию, банки
        // отказывают. Их адреса взяты целыми блоками анонсов, а не точками:
        // внутри блока сервис переезжает свободно.
        BypassNetwork("213.59.128.0/17", "Госуслуги — основной блок"),
        BypassNetwork("185.73.192.0/22", "Ozon — сайт, приложение и картинки"),
        BypassNetwork("31.130.128.0/19", "Ozon — оформление заказа и оплата"),
        BypassNetwork("194.9.208.0/22", "Ozon Банк — корзина, оплата, рассрочка"),
        BypassNetwork("213.180.192.0/19", "Кинопоиск и Яндекс"),
        BypassNetwork("5.255.192.0/18", "Яндекс — второй блок"),
        BypassNetwork("77.88.0.0/18", "Яндекс — третий блок"),
        BypassNetwork("84.252.144.0/21", "Сбербанк"),
        BypassNetwork("178.130.128.0/20", "Т-Банк (Тинькофф)"),
        BypassNetwork("195.242.82.0/23", "ВТБ"),
        BypassNetwork("217.12.96.0/20", "Альфа-Банк"),
        BypassNetwork("195.208.0.0/15", "Налоговая, Сбермаркет"),
        BypassNetwork("185.62.200.0/22", "Wildberries"),
        BypassNetwork("176.114.112.0/20", "Avito"),
        BypassNetwork("91.206.126.0/23", "Мегамаркет, СДЭК"),
        BypassNetwork("87.240.128.0/18", "VK"),
        BypassNetwork("93.186.224.0/20", "VK — второй блок"),
        BypassNetwork("95.163.0.0/17", "Одноклассники"),
        BypassNetwork("89.221.232.0/21", "Mail.ru"),
        BypassNetwork("90.156.224.0/19", "Mail.ru — второй блок"),
        BypassNetwork("185.180.200.0/22", "Mail.ru — третий блок"),
        BypassNetwork("109.238.88.0/22", "Rutube"),
        BypassNetwork("178.248.232.0/21", "Rutube, МТС"),
        BypassNetwork("80.67.40.0/22", "Иви"),
        BypassNetwork("185.169.152.0/22", "Okko"),
        BypassNetwork("91.236.48.0/22", "2ГИС"),
        BypassNetwork("94.124.192.0/20", "HeadHunter"),
        BypassNetwork("212.164.0.0/16", "Почта России, РЖД"),
        BypassNetwork("178.176.0.0/14", "Мегафон"),
        BypassNetwork("188.162.0.0/16", "Мегафон — второй блок"),
        BypassNetwork("217.118.64.0/19", "Билайн"),
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
