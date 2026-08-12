import Foundation

struct L10n {
    let tagline: String
    let loginPlaceholder: String
    let passwordPlaceholder: String
    let signIn: String
    let signingIn: String
    let signInDone: String
    let continueWithoutAccount: String
    let errEmptyLogin: String
    let errShortPassword: String
    let errBadKey: String
    let termsPrefix: String
    let termsLink: String

    let connected: String
    let connectingTxt: String
    let disconnected: String
    let tapToConnect: String
    let chooseServer: String

    let settings: String
    let split: String
    let splitDesc: String
    let addFile: String
    let kill: String
    let killDesc: String
    let autostart: String
    let autostartDesc: String
    let autoconnect: String
    let autoconnectDesc: String
    let logging: String
    let loggingDesc: String
    let language: String
    let langName: String
    let logout: String
    let logoutConfirmTitle: String
    let logoutConfirmMessage: String
    let yes: String
    let no: String

    let fileTitle: String
    let fileDesc: String
    let defaultMeta: String
    let entries: String
    let chooseFile: String
    let del: String
    let holdHint: String
    let importError: String

    let version: String
    let tgTitle: String
    let siteTitle: String
    let faqTitle: String
    let faqSub: String
    let rateTitle: String
    let rateSub: String
    let privacy: String
    let terms: String

    let ms: String

    static func of(_ lang: String) -> L10n { lang == "en" ? .en : .ru }

    static let ru = L10n(
        tagline: "Свободный и безопасный интернет",
        loginPlaceholder: "Логин",
        passwordPlaceholder: "Пароль",
        signIn: "Войти",
        signingIn: "Подключение…",
        signInDone: "✓ Готово",
        continueWithoutAccount: "Продолжить без входа",
        errEmptyLogin: "Введите логин",
        errShortPassword: "Пароль слишком короткий",
        errBadKey: "Не удалось применить ключ. Проверьте ключ и попробуйте ещё раз",
        termsPrefix: "Продолжая, вы принимаете ",
        termsLink: "условия сервиса",
        connected: "Подключено",
        connectingTxt: "Подключение…",
        disconnected: "Отключено",
        tapToConnect: "Нажмите, чтобы подключиться",
        chooseServer: "ВЫБЕРИТЕ СЕРВЕР",
        settings: "Настройки",
        split: "Раздельное туннелирование",
        splitDesc: "Обходит видимость VPN для РФ сервисов",
        addFile: "Добавить файл",
        kill: "Kill Switch",
        killDesc: "Блокировать интернет при обрыве VPN",
        autostart: "Автозапуск",
        autostartDesc: "Запускать приложение при старте устройства",
        autoconnect: "Автоподключение",
        autoconnectDesc: "Подключаться к VPN при запуске",
        logging: "Логирование",
        loggingDesc: "Сохранять журнал для диагностики",
        language: "Язык",
        langName: "Русский",
        logout: "Выйти из аккаунта",
        logoutConfirmTitle: "Уверены, что хотите выйти?",
        logoutConfirmMessage: "Для входа понадобится снова ввести данные аккаунта",
        yes: "Да",
        no: "Нет",
        fileTitle: "Файл туннелирования",
        fileDesc: "Список сайтов и приложений, которые идут через VPN. Форматы: .json или .txt — по одному домену или названию приложения на строку.",
        defaultMeta: "По умолчанию",
        entries: "записей",
        chooseFile: "Выбрать файл",
        del: "Удалить",
        holdHint: "Удерживайте файл, чтобы удалить его",
        importError: "Не удалось прочитать файл",
        version: "Версия 1.0.0",
        tgTitle: "Поддержка в Telegram",
        siteTitle: "Наш сайт",
        faqTitle: "Частые вопросы",
        faqSub: "Как настроить и решить проблемы",
        rateTitle: "Оценить приложение",
        rateSub: "App Store · Google Play",
        privacy: "Политика конфиденциальности",
        terms: "Условия",
        ms: "мс"
    )

    static let en = L10n(
        tagline: "Free and secure internet",
        loginPlaceholder: "Login",
        passwordPlaceholder: "Password",
        signIn: "Sign in",
        signingIn: "Connecting…",
        signInDone: "✓ Done",
        continueWithoutAccount: "Continue without account",
        errEmptyLogin: "Enter your login",
        errShortPassword: "Password is too short",
        errBadKey: "Couldn't apply the key. Check it and try again",
        termsPrefix: "By continuing you accept the ",
        termsLink: "terms of service",
        connected: "Connected",
        connectingTxt: "Connecting…",
        disconnected: "Disconnected",
        tapToConnect: "Tap to connect",
        chooseServer: "CHOOSE A SERVER",
        settings: "Settings",
        split: "Split tunneling",
        splitDesc: "Hides VPN usage from Russian services",
        addFile: "Add file",
        kill: "Kill Switch",
        killDesc: "Block internet if VPN drops",
        autostart: "Launch at startup",
        autostartDesc: "Open the app when the device starts",
        autoconnect: "Auto-connect",
        autoconnectDesc: "Connect to VPN on launch",
        logging: "Logging",
        loggingDesc: "Keep a diagnostics log",
        language: "Language",
        langName: "English",
        logout: "Log out",
        logoutConfirmTitle: "Sure you want to log out?",
        logoutConfirmMessage: "You'll need to enter your account details again",
        yes: "Yes",
        no: "No",
        fileTitle: "Tunneling file",
        fileDesc: "A list of sites and apps routed through the VPN. Formats: .json or .txt — one domain or app name per line.",
        defaultMeta: "Default",
        entries: "entries",
        chooseFile: "Choose file",
        del: "Delete",
        holdHint: "Press and hold a file to delete it",
        importError: "Couldn't read the file",
        version: "Version 1.0.0",
        tgTitle: "Telegram support",
        siteTitle: "Our website",
        faqTitle: "FAQ",
        faqSub: "Setup and troubleshooting",
        rateTitle: "Rate the app",
        rateSub: "App Store · Google Play",
        privacy: "Privacy policy",
        terms: "Terms",
        ms: "ms"
    )
}
