import Foundation

/// Строки интерфейса. Хранятся структурой, а не .strings: язык переключается
/// прямо в настройках, без перезапуска, а системный не всегда тот, на котором
/// человек хочет читать.
struct L10n {
    /// Код языка самой таблицы: правила склонения зависят от него, а сравнивать
    /// ради этого две сотни строк между собой — расточительно и хрупко.
    let code: String
    let tagline: String
    let loginPlaceholder: String
    let passwordPlaceholder: String
    let signIn: String
    let signingIn: String
    let orKey: String
    let keyPlaceholder: String
    let applyKey: String
    let errEmptyLogin: String
    let errShortPassword: String
    let errBadKey: String
    let termsPrefix: String
    let termsLink: String

    let connected: String
    let connecting: String
    let disconnected: String
    let disconnecting: String
    let tapToConnect: String
    let chooseServer: String
    let noServers: String
    let noServersHint: String
    let subscriptionOver: String
    let subscriptionDays: String

    // Подписка на главном экране: предупреждение и продление
    let trafficLowWarn: String
    let expiresSoonWarn: String
    let renew: String
    let dayOne: String
    let dayFew: String
    let dayMany: String
    let unitGb: String
    let unitMb: String

    let settings: String
    let back: String
    let split: String
    let splitDesc: String
    let kill: String
    let killDesc: String
    let launchAtLogin: String
    let launchAtLoginDesc: String
    let autoconnect: String
    let autoconnectDesc: String
    let useVPNDNS: String
    let useVPNDNSDesc: String
    let notifications: String
    let notificationsDesc: String
    let fileTitle: String
    let fileDesc: String
    let fileRow: String
    let defaultMeta: String
    let entries: String
    let addFile: String
    let chooseFile: String
    let del: String
    let holdHint: String
    let importError: String

    let language: String
    let langName: String
    let logout: String
    let logoutConfirmTitle: String
    let logoutConfirmMessage: String
    let yes: String
    let no: String

    let service: String
    let serviceInstalled: String
    let serviceMissing: String
    let installService: String
    let reinstallService: String
    let removeService: String

    // Обновление приложения
    let updateTitle: String
    let updateChecking: String
    let updateNone: String
    let updateCurrent: String
    let updateAvailableFmt: String
    let updateButton: String
    let updateDownloadingFmt: String
    let updateInstalling: String
    let updateFailed: String
    let updateBadFile: String
    let updateMandatory: String
    let updateMandatoryNoticeFmt: String
    let updateRestartHint: String

    let support: String
    let version: String
    let tgTitle: String
    let siteTitle: String
    let faqTitle: String
    let faqSub: String
    let downloadsTitle: String
    let downloadsSub: String
    let privacy: String
    let terms: String

    let connectAction: String
    let disconnectAction: String
    let quit: String
    let show: String
    let ms: String

    let errNoHandshake: String
    let errTunnelFailed: String
    let errTunnelDropped: String
    let errHelper: String
    let noticeRemoteSignout: String

    // Системные сообщения
    let notifConnectedTitle: String
    let notifDroppedTitle: String
    let notifDroppedBody: String
    let notifSignedOutTitle: String
    let notifTrafficTitle: String
    let notifExpiresTitle: String

    static func of(_ lang: String) -> L10n { lang == "en" ? .en : .ru }

    /// «Доступна версия 1.2.0»
    func updateAvailable(_ version: String) -> String {
        String(format: updateAvailableFmt, version)
    }

    func updateDownloading(_ percent: Int) -> String {
        String(format: updateDownloadingFmt, percent)
    }

    func updateMandatoryNotice(_ version: String) -> String {
        String(format: updateMandatoryNoticeFmt, version)
    }

    /// «Трафик заканчивается: осталось 1,4 ГБ»
    func trafficLow(_ left: String) -> String {
        String(format: trafficLowWarn, left)
    }

    /// «Подписка истекает через 3 дня»
    func expiresSoon(_ days: String) -> String {
        String(format: expiresSoonWarn, days)
    }

    /// Гигабайты и мегабайты — единицы, в которых человек думает о трафике.
    func bytes(_ value: Int64) -> String {
        if value <= 0 { return "0 \(unitMb)" }
        let gb = Double(value) / 1024 / 1024 / 1024
        if gb >= 1 { return String(format: "%.1f %@", gb, unitGb) }
        return String(format: "%.0f %@", Double(value) / 1024 / 1024, unitMb)
    }

    /// «3 дня» / «3 days».
    ///
    /// Русские окончания — по правилу (день/дня/дней), в английском форм две,
    /// и правило для них другое: 21 по-русски «день», по-английски — days.
    func days(_ count: Int) -> String {
        if code == "en" { return "\(count) " + (count == 1 ? dayOne : dayMany) }
        let n = abs(count) % 100
        let last = n % 10
        let word: String
        switch true {
        case (11...19).contains(n): word = dayMany
        case (2...4).contains(last): word = dayFew
        case last == 1: word = dayOne
        default: word = dayMany
        }
        return "\(count) \(word)"
    }

    static let ru = L10n(
        code: "ru",
        tagline: "Свободный и безопасный интернет",
        loginPlaceholder: "Логин",
        passwordPlaceholder: "Пароль",
        signIn: "Войти",
        signingIn: "Вход…",
        orKey: "или вставьте ключ доступа",
        keyPlaceholder: "vpn://… или конфиг wg-quick",
        applyKey: "Применить ключ",
        errEmptyLogin: "Введите логин",
        errShortPassword: "Пароль слишком короткий",
        errBadKey: "Не удалось прочитать ключ. Проверьте его и попробуйте ещё раз",
        termsPrefix: "Продолжая, вы принимаете ",
        termsLink: "условия сервиса",
        connected: "Подключено",
        connecting: "Подключение…",
        disconnected: "Отключено",
        disconnecting: "Отключение…",
        tapToConnect: "Нажмите, чтобы подключиться",
        chooseServer: "ВЫБЕРИТЕ СЕРВЕР",
        noServers: "Серверов нет",
        noServersHint: "Войдите в аккаунт или вставьте ключ доступа",
        subscriptionOver: "Подписка закончилась",
        subscriptionDays: "дн. подписки",
        trafficLowWarn: "Трафик заканчивается: осталось %@",
        expiresSoonWarn: "Подписка истекает через %@",
        renew: "Продлить",
        dayOne: "день",
        dayFew: "дня",
        dayMany: "дней",
        unitGb: "ГБ",
        unitMb: "МБ",
        settings: "Настройки",
        back: "Назад",
        split: "Раздельное туннелирование",
        splitDesc: "Российские сети идут напрямую: Госуслуги, банки и школьные порталы требуют местный адрес",
        kill: "Kill Switch",
        killDesc: "Обрывать трафик, если туннель упал",
        launchAtLogin: "Запуск при входе",
        launchAtLoginDesc: "Открывать приложение вместе с системой",
        autoconnect: "Автоподключение",
        autoconnectDesc: "Подключаться сразу при запуске",
        useVPNDNS: "DNS из конфига",
        useVPNDNSDesc: "Подменять системные DNS на серверные",
        notifications: "Уведомления",
        notificationsDesc: "Сообщать об обрыве связи, конце трафика и обновлениях",
        fileTitle: "Файл туннелирования",
        fileDesc: "Список сетей, которые идут напрямую, мимо VPN. Форматы: .json (как в приложении для Android) или .txt — по одной сети на строку.",
        fileRow: "Список сетей",
        defaultMeta: "Встроенный",
        entries: "сетей",
        addFile: "Добавить файл",
        chooseFile: "Выбрать",
        del: "Удалить",
        holdHint: "Правой кнопкой по файлу — удалить. Встроенный список удалить нельзя.",
        importError: "Не удалось добавить файл",
        language: "Язык",
        langName: "Русский",
        logout: "Выйти из аккаунта",
        logoutConfirmTitle: "Выйти из аккаунта?",
        logoutConfirmMessage: "Соединение разорвётся, для входа понадобятся логин и пароль",
        yes: "Выйти",
        no: "Отмена",
        service: "Служба подключения",
        serviceInstalled: "Установлена и работает",
        serviceMissing: "Не установлена — VPN не поднимется",
        installService: "Установить",
        reinstallService: "Переустановить",
        removeService: "Удалить службу",
        updateTitle: "Обновление",
        updateChecking: "Проверяем обновления…",
        updateNone: "Установлена последняя версия",
        updateCurrent: "Сейчас установлена",
        updateAvailableFmt: "Доступна версия %@",
        updateButton: "Обновить",
        updateDownloadingFmt: "Скачиваем… %d%%",
        updateInstalling: "Проверяем и ставим…",
        updateFailed: "Обновиться не получилось — проверьте связь и попробуйте ещё раз",
        updateBadFile: "Файл обновления не сошёлся с контрольной суммой — попробуйте ещё раз",
        updateMandatory: "Без этого обновления VPN работать не будет",
        updateMandatoryNoticeFmt: "Вышла версия %@ — без неё VPN работать не будет",
        updateRestartHint: "Приложение закроется и откроется уже новым",
        support: "Поддержка",
        version: "Версия",
        tgTitle: "Поддержка в Telegram",
        siteTitle: "Наш сайт",
        faqTitle: "Частые вопросы",
        faqSub: "Настройка и решение проблем",
        downloadsTitle: "Другие устройства",
        downloadsSub: "iPhone, Android, Windows",
        privacy: "Политика конфиденциальности",
        terms: "Условия",
        connectAction: "Подключить",
        disconnectAction: "Отключить",
        quit: "Выйти из приложения",
        show: "Открыть Prosto VPN",
        ms: "мс",
        errNoHandshake: "Сервер не отвечает. Возможно, сеть блокирует VPN — попробуйте другую страну или другую сеть",
        errTunnelFailed: "Не удалось поднять туннель. Проверьте службу подключения и попробуйте ещё раз",
        errTunnelDropped: "Соединение с VPN прервалось",
        errHelper: "Служба подключения недоступна",
        noticeRemoteSignout: "Это устройство отключили в личном кабинете. Войдите снова, чтобы продолжить",
        notifConnectedTitle: "VPN подключён",
        notifDroppedTitle: "VPN отключился",
        notifDroppedBody: "Соединение прервалось. Трафик снова идёт без VPN",
        notifSignedOutTitle: "Устройство отключили",
        notifTrafficTitle: "Трафик заканчивается",
        notifExpiresTitle: "Подписка заканчивается"
    )

    static let en = L10n(
        code: "en",
        tagline: "Free and secure internet",
        loginPlaceholder: "Login",
        passwordPlaceholder: "Password",
        signIn: "Sign in",
        signingIn: "Signing in…",
        orKey: "or paste an access key",
        keyPlaceholder: "vpn://… or a wg-quick config",
        applyKey: "Apply key",
        errEmptyLogin: "Enter your login",
        errShortPassword: "Password is too short",
        errBadKey: "Couldn't read the key. Check it and try again",
        termsPrefix: "By continuing you accept the ",
        termsLink: "terms of service",
        connected: "Connected",
        connecting: "Connecting…",
        disconnected: "Disconnected",
        disconnecting: "Disconnecting…",
        tapToConnect: "Click to connect",
        chooseServer: "CHOOSE A SERVER",
        noServers: "No servers",
        noServersHint: "Sign in or paste an access key",
        subscriptionOver: "Subscription expired",
        subscriptionDays: "days left",
        trafficLowWarn: "Traffic is running out: %@ left",
        expiresSoonWarn: "Subscription expires in %@",
        renew: "Renew",
        dayOne: "day",
        dayFew: "days",
        dayMany: "days",
        unitGb: "GB",
        unitMb: "MB",
        settings: "Settings",
        back: "Back",
        split: "Split tunneling",
        splitDesc: "Russian networks go direct: state portals and banks require a local address",
        kill: "Kill Switch",
        killDesc: "Cut traffic if the tunnel drops",
        launchAtLogin: "Launch at login",
        launchAtLoginDesc: "Open the app together with the system",
        autoconnect: "Auto-connect",
        autoconnectDesc: "Connect right after launch",
        useVPNDNS: "DNS from config",
        useVPNDNSDesc: "Replace system DNS with the server's",
        notifications: "Notifications",
        notificationsDesc: "Tell about dropped connections, traffic and updates",
        fileTitle: "Tunneling file",
        fileDesc: "Networks that go directly, bypassing the VPN. Formats: .json (same as the Android app) or .txt — one network per line.",
        fileRow: "Network list",
        defaultMeta: "Built-in",
        entries: "networks",
        addFile: "Add file",
        chooseFile: "Choose",
        del: "Delete",
        holdHint: "Right-click a file to delete it. The built-in list can't be removed.",
        importError: "Couldn't add the file",
        language: "Language",
        langName: "English",
        logout: "Log out",
        logoutConfirmTitle: "Log out?",
        logoutConfirmMessage: "The tunnel will drop and you'll need your credentials again",
        yes: "Log out",
        no: "Cancel",
        service: "Connection service",
        serviceInstalled: "Installed and running",
        serviceMissing: "Not installed — the VPN can't start",
        installService: "Install",
        reinstallService: "Reinstall",
        removeService: "Remove service",
        updateTitle: "Update",
        updateChecking: "Checking for updates…",
        updateNone: "You are on the latest version",
        updateCurrent: "Currently installed",
        updateAvailableFmt: "Version %@ is available",
        updateButton: "Update",
        updateDownloadingFmt: "Downloading… %d%%",
        updateInstalling: "Verifying and installing…",
        updateFailed: "The update didn't go through — check your connection and try again",
        updateBadFile: "The update file didn't match its checksum — try again",
        updateMandatory: "The VPN won't work without this update",
        updateMandatoryNoticeFmt: "Version %@ is out — the VPN won't work without it",
        updateRestartHint: "The app will close and open again updated",
        support: "Support",
        version: "Version",
        tgTitle: "Telegram support",
        siteTitle: "Our website",
        faqTitle: "FAQ",
        faqSub: "Setup and troubleshooting",
        downloadsTitle: "Other devices",
        downloadsSub: "iPhone, Android, Windows",
        privacy: "Privacy policy",
        terms: "Terms",
        connectAction: "Connect",
        disconnectAction: "Disconnect",
        quit: "Quit Prosto VPN",
        show: "Open Prosto VPN",
        ms: "ms",
        errNoHandshake: "The server isn't responding. The network may be blocking VPN — try another country or another network",
        errTunnelFailed: "Couldn't bring the tunnel up. Check the connection service and try again",
        errTunnelDropped: "VPN connection dropped",
        errHelper: "Connection service is unavailable",
        noticeRemoteSignout: "This device was disconnected in the account dashboard. Sign in again to continue",
        notifConnectedTitle: "VPN connected",
        notifDroppedTitle: "VPN disconnected",
        notifDroppedBody: "The connection dropped. Traffic goes without VPN again",
        notifSignedOutTitle: "Device disconnected",
        notifTrafficTitle: "Traffic is running out",
        notifExpiresTitle: "Subscription is ending"
    )
}
