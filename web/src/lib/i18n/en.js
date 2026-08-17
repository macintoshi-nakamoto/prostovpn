/*
 * English strings. Mirrors ru.js key for key: a key that exists here and not
 * there (or the other way round) is a bug — t() falls back to Russian and the
 * page ends up bilingual mid-sentence.
 *
 * Plural entries carry one/other instead of the Russian one/few/many; t()
 * picks the form by language, so both shapes live side by side without the
 * call sites knowing which language is on.
 */
export const en = {
  units: {
    days: { one: "{count} day", other: "{count} days" },
    months: { one: "{count} month", other: "{count} months" },
    years: { one: "{count} year", other: "{count} years" },
    devices: { one: "{count} device", other: "{count} devices" },
    devicesGen: { one: "{count} device", other: "{count} devices" },
    countries: { one: "{count} country", other: "{count} countries" },
    connections: { one: "{count} connection", other: "{count} connections" },
  },

  controls: {
    language: "Language",
    languageSwitch: "Переключить на русский",
    themeToDark: "Dark theme",
    themeToLight: "Light theme",
  },

  nav: {
    speed: "Speed",
    app: "App",
    plans: "Pricing",
    security: "Security",
    guide: "Setup",
    faq: "FAQ",
    account: "Account",
    signin: "Sign in",
  },

  landing: {
    upTo: "up to {value}",

    hero: {
      line1: "The internet",
      line2: "without borders",
      lead:
        "One tap to connect, 60+ countries and speeds up to 1 Gbps. No logs, no setup " +
        "and no throttling.",
      primary: "Get started",
      ghost: "How it works",
      platforms: "iOS · Android · macOS · Windows · TV",
    },

    features: {
      speed: { title: "Up to 1 Gbps", text: "No throttling, even at peak hours" },
      countries: { title: "60+ countries", text: "Over 900 servers on five continents" },
      devices: { text: "One subscription for the whole family" },
      logs: { title: "No logs", text: "We keep no record of what you connect to" },
    },

    zero: {
      title: "records",
      subtitle: "of your traffic",
      text:
        "Servers run entirely in RAM: a reboot leaves nothing behind. The policy is " +
        "confirmed by an independent audit.",
      button: "Get Prosto VPN",
    },

    app: {
      line1: "An app",
      line2: "that simply",
      line3: "works",
      text:
        "One button on the home screen. Everything else is automatic: the best server, " +
        "bypassing blocks and staying protected when you switch to Wi-Fi.",
      laptopAlt: "Prosto VPN on a laptop",
    },

    split: {
      line1: "Russian services",
      line2: "keep working as usual",
      text:
        "Built-in split tunnelling keeps banks, marketplaces and government services on a " +
        "direct connection while the rest of your traffic goes through the VPN. Nothing to " +
        "switch on by hand.",
      note:
        "The service list updates itself — new apps land in the exceptions without a VPN " +
        "update.",
      button: "Connect",
      cards: [
        { title: "Banks", text: "Apps and transfers open without geolocation errors" },
        { title: "Marketplaces", text: "Orders, payment and delivery work as they normally do" },
        {
          title: "Government services",
          text: "SMS sign-in and confirmations go through the first time",
        },
        { title: "Taxi and delivery", text: "Maps and addresses resolve to the city you're in" },
      ],
    },

    plans: {
      line1: "One plan.",
      line2: "Everything included",
      lead: "The longer the term, the lower the monthly price. Cancel any time.",
      trialTag: "Free",
      trialTitle: "Free trial",
      trialHead: "{title}: {term} and {traffic}",
      trialNote: "Create an account — access opens right away, no payment card needed.",
      trialButton: "Try for free",
      trialButtonAuthed: "My plan",
      perMonth: "/ mo",
      choose: "Choose",
      priceFor: "{price} for {term}",
      unlimited: "Unlimited traffic",
      unlimitedShort: "unlimited traffic",
      traffic: "{size} of traffic",
      fine:
        "Devices are counted as simultaneous sign-ins: signing in on one too many drops the " +
        "oldest session rather than refusing you. When the included traffic runs out, access " +
        "closes until you renew — the app warns you in advance, once less than 5 GB is left.",
    },

    shield: {
      line1: "The Prosto",
      line2: "shield",
      button: "Learn more",
      items: [
        {
          title: "AES-256 encryption",
          text: "The same standard banks use. WireGuard and OpenVPN, your choice.",
        },
        {
          title: "DNS leak protection",
          text: "Queries leave only through the tunnel: your ISP can't see the sites you open.",
        },
        {
          title: "Independent audit",
          text: "An outside team reviews the infrastructure and the no-logs policy every year.",
        },
      ],
    },

    devices: {
      title: "One subscription — every device",
      text: "iPhone, Android, Mac, Windows and TV. Simultaneous connections — {devices}.",
    },

    privacy: {
      eyebrow: "PRIVACY",
      line1: "We have nothing",
      line2: "to hand over",
      items: [
        "We don't see what you open. The app keeps no log of sites or addresses, and the nodes run in RAM: a reboot leaves nothing behind. There is nothing to hand over on request — whoever makes it — because what was never collected doesn't exist.",
        "A login and a password are enough. No passport, no phone number, no social accounts. Email is optional — it only matters if you want renewal notices; pay in crypto and nothing ties you to a card.",
        "We don't sell or share data — not with ad networks, not with analytics, not with any government. There are no third-party trackers on the site.",
      ],
      sign: "The project is run by anonymous enthusiasts: no office, no legal entity and no names anyone could be asked about.",
    },

    docs: {
      line1: "Transparent",
      line2: "all the way",
      lead: "Everything worth reading before you connect",
      items: [
        { title: "No-logs policy", text: "What we don't collect, and why" },
        { title: "Subscription terms", text: "Payment, renewal and refunds" },
        { title: "FAQ", text: "How a VPN works and what to do when it doesn't" },
        { title: "Contacts", text: "Support and feedback" },
      ],
    },
  },

  footer: {
    plans: "Pricing",
    app: "App",
    servers: "Servers",
    security: "Security",
    faq: "FAQ",
    guide: "Setup",
    support: "Support",
    bot: "Telegram bot",
    channel: "Telegram channel",
    terms: "Terms",
    privacy: "Privacy",
    contacts: "Contacts",
    aup: "Acceptable use",
    refund: "Refunds",
    licenses: "Licenses",
    supportNote: "Telegram support replies fast — a few minutes on average",
    email: "Email",
  },

  guide: {
    breadcrumbHome: "Home",
    breadcrumbCurrent: "Setup",
    title: "How to connect Prosto VPN",
    lead: "A few steps and one minute on any device. Pick your platform — we'll show exactly your sequence.",
    reading: "2 minute read",
    updated: "Updated 18 August 2026",

    platforms: {
      android: "Android",
      ios: "iPhone",
      mac: "Mac",
      win: "Windows",
      tv: "TV",
    },

    soon: "Soon",
    downloadFallback: "Download",

    os: {
      android: {
        title: "Connecting on Android",
        appTitle: "Prosto VPN for Android",
        appText: "A single file from the site: no Google Play needed, updates come from the app itself.",
        download: "Download APK",
        steps: [
          ["Download the APK", "Our Android app comes as one file from the site — Google Play is not involved."],
          ["Allow the install", "Android will ask about installing from this source — confirm. The file is signed by us."],
          ["Sign in", "Open the app and enter the login and password from your account."],
          ["Confirm the system prompt", "Android will ask to create a VPN connection — tap OK."],
          ["Press connect", "Split tunneling is already inside: Russian services go direct, everything else through the tunnel."],
        ],
      },
      ios: {
        title: "Connecting on iPhone and iPad",
        appTitle: "AmneziaVPN for iPhone and iPad",
        appText: "We don't have our own iPhone app yet, so you connect with a key through the free AmneziaVPN.",
        download: "Open the App Store",
        steps: [
          ["Install AmneziaVPN", "Find AmneziaVPN in the App Store or open the link above right on the device. The app is free."],
          ["Get your Prosto key", "We issue the key — it waits in your account and in the Telegram bot."],
          ["Paste the key into the app", "On the Connection screen paste the string into Insert key and tap Insert. The config is recognised on its own."],
          ["Tap Connect", "On the New connection screen confirm it. iOS will ask to allow the VPN profile — agree."],
          ["Check the status", "The circle turns orange and says Connected, with the Prosto VPN server below."],
        ],
        shots: [
          "Paste the key into Insert key and tap Insert",
          "The app recognises the config — tap Connect",
          "Done: Connected and the Prosto VPN server",
        ],
      },
      mac: {
        title: "Connecting on macOS",
        appTitle: "Prosto VPN for macOS",
        appText: "One image, works on Apple Silicon and Intel. Updates come from the app itself.",
        download: "Download DMG",
        steps: [
          ["Download the image", "The .dmg works on both Apple Silicon and Intel."],
          ["Move it to Applications", "Open the image and drag Prosto VPN into the Applications folder."],
          ["Sign in", "Open the app and enter the login and password from your account."],
          ["Allow the connection service", "On the first connect macOS asks for the administrator password once: a tunnel cannot be raised without root."],
          ["Press connect", "Split tunneling is already inside: Russian services go direct, everything else through the tunnel."],
        ],
      },
      win: {
        title: "Connecting on Windows",
        appTitle: "Prosto VPN for Windows",
        appText: "One installer, Windows 10 and 11. The tunnel driver installs itself.",
        download: "Download the installer",
        steps: [
          ["Download the installer", "Windows 10 and 11 are supported, no separate VPN client needed."],
          ["Run the setup", "The tunnel driver installs automatically, no reboot required."],
          ["Sign in", "Open the app and enter the login and password from your account."],
          ["Confirm the system prompt", "Windows will ask permission to create a VPN connection — agree."],
          ["Press connect", "Split tunneling is already inside: Russian services go direct, everything else through the tunnel."],
        ],
      },
      tv: {
        title: "Connecting on a TV",
        appTitle: "Prosto VPN for Android TV",
        appText: "The same file as for Android: no separate TV build needed.",
        download: "Download APK",
        steps: [
          ["Download the APK on a computer", "The button above. It's the same file as for the phone."],
          ["Copy it to a USB stick", "Put the APK on a regular USB stick and plug it into the TV."],
          ["Install from the stick", "Open the file manager on the TV, find the APK and start the install. Allow unknown sources if asked."],
          ["Sign in with login and password", "The same ones as in your account. The on-screen keyboard works from the remote; case matters."],
          ["Confirm and connect", "The TV will ask permission for the VPN connection — confirm and press connect. For streaming pick the country of the catalogue you want."],
        ],
      },
    },

    shotsTitle: "How it looks in the app",
    done: "Done. The connection icon turns orange — traffic goes through the encrypted tunnel.",
    toAccount: "Account",

    asideKeyTitle: "Where to get the key",
    asideKeyText: "The key waits in your account and in the Telegram bot. One key works on every device of the account.",
    asideLoginTitle: "Sign-in details",
    asideLoginText: "You need the login and password of your Prosto VPN account — the same ones as in the dashboard. Forgot the password — change it there.",
    asideBot: "Telegram bot",
    asideNeedTitle: "What you'll need",
    asideNeedText: "A Prosto VPN account, an internet connection and a minute. No card required.",
    asideCreate: "Create an account",

    split: {
      eyebrow: "SPLIT TUNNELING",
      title: "Russian services keep working",
      lead1: "Split tunneling sends through the VPN only the addresses that need it. The rest goes direct, so banks, state portals, marketplaces and delivery keep working: they see a normal local address and don't block the login.",
      lead2: "In our apps the list is already inside and on by default — nothing to set up. The steps below are for AmneziaVPN on iPhone, where the list is imported by hand.",
      fileButton: "Get the list in your account",
      botButton: "Get it from the bot",
      steps: [
        ["Download the address list", "In your account or in the bot — a file with Russian ranges."],
        ["Open split tunneling", "In AmneziaVPN the section lives in the connection settings."],
        ["Choose the list mode", "«Addresses from the list should not open through the VPN» — Russian networks go direct, the rest stays in the tunnel."],
        ["Import the file", "Advanced settings → Import → replace the site list. Done."],
      ],
      shots: [
        "The section in connection settings",
        "Mode: list goes around the VPN",
        "Advanced settings → Import",
        "Replace the site list",
      ],
    },

    help: {
      title: "If something doesn't work",
      lead: "Three reasons that close almost every request",
      cards: [
        ["It won't connect", "Switch the country in the server list and try again. Mobile data instead of Wi-Fi often helps too: networks block VPN differently."],
        ["Slow speed", "Pick another country — the closest one isn't always the fastest. Speed depends on node load more than on distance."],
        ["Banking apps fail", "Turn on split tunneling: local addresses go direct, and the apps stop seeing a foreign address."],
      ],
      askTitle: "Still have questions?",
      askText: "Write to Telegram or email — we answer in both",
      askBot: "Support in Telegram",
    },
  },

  login: {
    title: "Sign in to your account",
    titleSignup: "Create an account",
    help: "Need help?",
    helpLink: "support",
    tabSignin: "Sign in",
    tabSignup: "Sign up",
    headSignin: "Welcome back",
    headSignup: "Create an account",
    subSignin: "Enter the login and password for your Prosto VPN account",
    subSignup: "A login and a password is all it takes. Email can come later",
    fieldLogin: "Login",
    fieldPassword: "Password",
    fieldRepeat: "Repeat password",
    placeholderPassword: "Your password",
    placeholderNewPassword: "At least 8 characters",
    placeholderRepeat: "The same password again",
    remember: "Keep me signed in",
    forgot: "Forgot password?",
    show: "Show",
    hide: "Hide",
    acceptBefore: "I accept the",
    acceptTerms: "subscription terms",
    acceptAnd: "and the",
    acceptPrivacy: "privacy policy",
    submitSignin: "Sign in",
    submitSignup: "Sign up",
    busySignin: "Signing in…",
    busySignup: "Creating…",
    switchToSignup: "No account yet?",
    switchToSignin: "Already have an account?",
    errors: {
      empty: "Fill in the login and password",
      short: "The password must be at least 8 characters",
      mismatch: "Passwords don't match",
      accept: "You need to accept the terms",
      loginTaken: "That login is taken — pick another one",
      loginInvalid: "A login may contain only Latin letters, digits, hyphen, dot and underscore",
      badCredentials: "Wrong login or password",
      throttled: "Too many attempts. Try again later",
      signupClosed: "Registration is closed right now",
      unknown: "Something went wrong. Please try again",
    },
  },

  account: {
    tabs: { account: "Account", plan: "Subscription", setup: "Setup guide" },
    heads: {
      account: ["Account", "Subscription, devices and sign-in details"],
      plan: ["Subscription", "Plan, payments and renewal"],
      setup: ["Setup guide", "Step by step for every platform"],
    },
    loadError: "Couldn't load the account data",
    fallbackName: "account",
    active: "Subscription active",
    inactive: "Subscription inactive",
    changePassword: "Change password",
    signOut: "Sign out",

    noPlan: "No plan",
    validUntil: "Valid until {date}",
    validUntilLeft: "Valid until {date} · {left} left",
    subscribePrompt: "Take out a subscription to get started",
    manage: "Manage subscription",

    statDevices: "Devices",
    statOf: "{used} of {total}",
    freeSlots: "{value} free",
    noSlots: "No slots left",
    statTraffic: "Traffic",
    trafficOf: "of {total}",
    trafficUnlimited: "Unlimited on this plan",
    statPublicId: "Public ID",
    publicIdHint: "Quote it when you contact support",

    devicesTitle: "Connected devices",
    devicesAdd: "Add",
    devicesEmpty:
      "No devices yet. Install the app and sign in with the same login and password.",
    thisDevice: "this device",
    disconnect: "Disconnect",
    disconnectConfirm: "Yes, disconnect",
    disconnectPartly:
      "The token is revoked, but one server did not answer — access there may take a moment to drop.",
    disconnectFailed: "Could not disconnect the device",
    deviceConnected: "online",
    deviceFallback: "Device",
    platformWeb: "Browser",

    dataTitle: "Account details",
    fieldLogin: "Login",
    fieldPassword: "Password",
    fieldEmail: "Email for receipts",
    emailEmpty: "not set",
    emailChange: "change",
    emailAdd: "add",
    save: "Save",
    cancel: "Cancel",
    emailTaken: "That email is already linked to another account",
    emailFailed: "Couldn't save the email",

    planTitle: "Plan",
    planTerm: "Term",
    planUntil: "Valid until",
    planLeft: "Remaining",
    renewTitle: "Renew subscription",
    renewText: "Renewing adds {term} to your current subscription.",
    renewPrice: " Price — {price}.",
    renewTermFallback: "the plan's term",
    renew: "Renew",
    renewBusy: "Creating order…",
    renewCreated:
      "The renewal order has been created. Payment is being connected — we'll write when it works.",
    renewFailed: "Couldn't create the order",
    switchTitle: "Switch to {plan}",
    switchText: "Payment opens {term} of access. Price — {price}.",
    switchAction: "Buy",
    paymentsTitle: "Payment history",
    paymentsEmpty: "No payments yet.",
    payDate: "Date",
    payDesc: "Description",
    paySum: "Amount",
    payFallback: "Payment",
  },

  setup: {
    moreGuide: "Full setup guide with screenshots",
    noteLabel: "Signing in to the app",
    note:
      "Signing in is the same on every platform: login {login} and the password for this " +
      "account. No keys and no config files — the app pulls the country list itself.",
    soon: "Soon",
    helpText: "Something won't connect? Telegram support replies fast.",
    windows: {
      title: "Installing on Windows",
      button: "Download for Windows",
      steps: [
        ["Download the installer", "Windows 10 and 11 are supported. The .msi takes under a minute."],
        ["Run the file", "The tunnel driver installs automatically and the app appears in the Start menu."],
        ["Sign in", "Use the same login and password as here, in your account."],
        ["Press the connect button", "A server is picked for you, or choose a country by hand."],
      ],
    },
    ios: {
      title: "Installing on iPhone and iPad",
      button: "Open the App Store",
      steps: [
        ["Download the app", "Find Prosto VPN in the App Store on the device itself."],
        ["Sign in", "The login and password are the same as here, in your account."],
        ["Allow the VPN configuration", "iOS asks you to confirm adding the profile — tap “Allow”."],
        ["Press the connect button", "A server is picked automatically."],
      ],
    },
    android: {
      title: "Installing on Android",
      button: "Open Google Play",
      steps: [
        ["Download the app", "Prosto VPN is on Google Play; for devices without Google services there's an APK on the site."],
        ["Sign in", "Use the login and password from your account."],
        ["Confirm the system prompt", "Android asks permission to create a VPN connection — tap “OK”."],
        ["Turn on autostart", "In the app settings, enable connecting when the system starts."],
      ],
    },
    macos: {
      title: "Installing on macOS",
      button: "Download for macOS",
      steps: [
        ["Download the installer", "The .dmg works on both Apple Silicon and Intel."],
        ["Move it to Applications", "Open the image and drag Prosto VPN into the Applications folder."],
        ["Sign in and allow the profile", "On first launch macOS asks for an administrator password."],
        ["Pin it to the menu bar", "The menu bar icon connects in one click."],
      ],
    },
  },

  password: {
    title: "Change password",
    sub:
      "Changing it signs out every device — you'll need to enter the new password again in " +
      "each app.",
    current: "Current password",
    next: "New password",
    repeat: "Repeat the new one",
    placeholder: "At least 8 characters",
    short: "The new password must be at least 8 characters",
    mismatch: "Passwords don't match",
    failed: "Couldn't change the password",
    cancel: "Cancel",
    submit: "Change",
    busy: "Changing…",
  },

  notFound: {
    title: "There's no such page",
    text: "Maybe the address has a typo — or the page has moved.",
    home: "Go home",
    account: "Go to my account",
  },

  legal: {
    notFoundAnswer: "Didn't find an answer?",
    writeSupport: "Message support",
    back: "Back home",

    faq: {
      eyebrow: "Help",
      title: "Frequently asked questions",
      lead: "Everything people usually ask on day one.",
      blocks: [
        {
          h: "Getting started",
          items: [
            [
              "I've paid. What now?",
              "You registered a login and a password. Download the app, type in those two lines — that's it. No config files and no keys: the app pulls the country list from your account itself. If anything is unclear, the Setup page walks through every step for Android, iPhone, Mac, Windows and TV, with screenshots.",
            ],
            [
              "How many devices can I sign in on?",
              "As many as the plan includes — the number is on its card. The desktop and phone apps work at the same time under one login and password. Signing in on one too many isn't refused: the oldest session is dropped, and you just sign in again there.",
            ],
            [
              "Can I try it for free?",
              "Yes. Registration opens a trial period — the term and traffic allowance are listed on the pricing page, and no payment card is needed.",
            ],
          ],
        },
        {
          h: "Connecting",
          items: [
            [
              "Windows asks for administrator rights",
              "That's normal and happens once, on connect. The app brings up a network adapter and the tunnel service, which an ordinary user isn't allowed to do.",
            ],
            [
              "It won't connect",
              "Close other VPNs, try a different country or a different network. The app prints the reason right on screen — quote it to support and we'll fix it faster.",
            ],
            [
              "What is split tunnelling?",
              "A switch in the settings: Russian services go direct, the rest of the traffic goes through the VPN. Note that Kill Switch doesn't work while it's on.",
            ],
          ],
        },
        {
          h: "Subscription",
          items: [
            [
              "How do I renew?",
              "In your account — same login and password as in the app. When a few days are left, the app shows a renew button by itself.",
            ],
            [
              "What happens when the subscription ends?",
              "The country list goes empty. The account stays yours: pay and everything comes back, with nothing to enter again.",
            ],
            [
              "What happens when the traffic runs out?",
              "Access closes the same way as non-payment: the connection drops and the country list empties. The app warns you in advance — once less than 5 GB is left it shows the remainder and a renew button. The counter resets when you renew.",
            ],
          ],
        },
        {
          h: "The app",
          items: [
            [
              "How do I update?",
              "By itself. When a new version is out, an exclamation mark appears on the settings button and an “Update” button appears in the settings. The app downloads it, verifies it and restarts as the new version.",
            ],
            [
              "I forgot my password",
              "Write to support from the email you signed up with — we'll tell you the password again or issue a new one.",
            ],
          ],
        },
      ],
    },

    terms: {
      eyebrow: "Documents",
      title: "Subscription terms",
      lead: "Briefly, how payment, renewal and refunds work.",
      blocks: [
        {
          h: "Subscription",
          items: [
            ["What's included", "Access to the service's servers for the term of the chosen plan; the number of devices and the traffic allowance are set by the plan."],
            ["Renewal", "The subscription renews when you act on it in your account. There are no automatic charges without your consent."],
            ["End of term", "Access closes, the account is kept. Pay and access returns with the same login and password."],
          ],
        },
        {
          h: "Payment and refunds",
          items: [
            ["Accepting payment", "Payment acceptance is being connected. Current methods are always shown on the pricing page."],
            ["Refunds", "Write to support — we look at each case individually and refund you if the service didn't suit you."],
          ],
        },
        {
          h: "Limits",
          items: [
            ["Fair use", "The service is for personal internet access. Reselling access and sending bulk mail from our addresses are not allowed."],
            ["Suspension", "We may close access if these terms are broken, with a warning through support."],
          ],
        },
      ],
    },

    privacy: {
      eyebrow: "Documents",
      title: "Privacy",
      lead: "What data we keep, and what we deliberately don't.",
      blocks: [
        {
          h: "What we don't keep",
          items: [
            ["Connection history", "We keep no log of the sites and addresses you open through the tunnel."],
            ["Traffic contents", "Traffic is encrypted on your device; there is nothing on our side to decrypt it with."],
          ],
        },
        {
          h: "What we do keep",
          items: [
            ["The account", "Login, hashed password, subscription term and payments — access can't be provided without them."],
            ["Devices", "The list of sign-ins: platform, app version and time of last activity — to keep to the device limit."],
            ["Traffic volume", "Total bytes for the period — for the plan's limits. No per-site breakdown."],
          ],
        },
        {
          h: "Sharing with third parties",
          items: [
            ["With nobody", "We don't sell or hand over data to third parties. The only processors are the ones without which payment and email delivery are impossible."],
          ],
        },
      ],
    },

    contacts: {
      eyebrow: "Support",
      title: "Get in touch",
      lead: "Telegram is fastest. Write from the email or the account you signed up with.",
      blocks: [
        {
          h: "Where to write",
          items: [
            ["Telegram", "@prostovpnn_bot — the main support channel, we reply quickly."],
            ["Email", "support@prostovpn.cc — when a messenger is inconvenient; the reply lands on the same address."],
            ["What to include", "Your login or the public ID from your account, the device, and whatever the app shows on screen."],
          ],
        },
      ],
    },
  },
};
