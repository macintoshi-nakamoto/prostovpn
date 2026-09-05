/* Guide — the current part of the dictionary, spread into `guide` in en.js. */
export const guideEn = {
  lead: "Pick your device — we'll show exactly your sequence. It takes a minute: the app already knows the countries, keys and settings.",
  reading: "3 minute read",
  updated: "Updated 5 September 2026",

  os: {
    android: {
      title: "Connecting on Android",
      appTitle: "Prosto VPN for Android",
      appText: "One file from the site, no Google Play. Two ways to connect inside, updates come from the app itself.",
      download: "Download APK",
      steps: [
        ["Download the APK", "The button above or “Download the app” in the dashboard. The file is signed by us, Google Play is not involved."],
        ["Allow the install", "Android asks about installing from this source — confirm. It's a one-time permission."],
        ["Sign in", "The same login and password as in the dashboard. Countries and settings come from the account."],
        ["Confirm the system prompt", "Android asks to create a VPN connection — tap OK. Allow notifications: without them the system doesn't see the VPN running."],
        ["Press connect", "The app picks the fast path and, if the network blocks it, switches to the backup one. Half a minute and you're connected."],
        ["Bank outside the VPN", "Settings → “Apps outside VPN”: tick the bank and government apps, their traffic goes direct. The rest stays in the tunnel."],
      ],
    },
    ios: {
      title: "Connecting on iPhone and iPad",
      appTitle: "AmneziaVPN or Happ for iPhone",
      appText: "No app of ours for iPhone — connect through free ones. AmneziaVPN takes a key, Happ takes a link; the dashboard issues both.",
      download: "Open the App Store",
      steps: [
        ["Install the app", "AmneziaVPN or Happ from the App Store. Not found with a Russian Apple ID — open the tip below, two ways there."],
        ["Get the key in the dashboard", "“Keys” → “Add key”: pick a country, the dashboard issues a vpn:// string and a QR code. For Happ — a subscription link, same place."],
        ["Paste it into the app", "AmneziaVPN: Connection screen → Insert key → Insert. Happ: “Add subscription” → paste the link. Everything is recognised on its own."],
        ["Tap Connect", "iOS asks to allow the VPN profile — agree. Once."],
        ["Check the status", "In AmneziaVPN the circle turns orange and says Connected. In Happ the best server and a toggle appear."],
        ["Russian sites", "In Happ they go direct right away. In AmneziaVPN the list is imported by hand — steps in the “Banks” section below."],
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
      appText: "One image for Apple Silicon and Intel. Updates come from the app itself.",
      download: "Download DMG",
      steps: [
        ["Download the image", "The .dmg works on both Apple Silicon and Intel."],
        ["Move it to Applications", "Open the image and drag Prosto VPN into the Applications folder."],
        ["Sign in", "The same login and password as in the dashboard."],
        ["Allow the connection service", "On the first connection macOS asks for the administrator password once: a tunnel can't be raised without it. The password stays on your computer."],
        ["Press connect", "Split tunneling is built in: Russian services go direct, everything else through the tunnel."],
      ],
    },
    win: {
      title: "Connecting on Windows",
      appTitle: "Prosto VPN for Windows",
      appText: "One installer, Windows 10 and 11. The tunnel driver installs itself, two ways to connect inside.",
      download: "Download the installer",
      steps: [
        ["Download the installer", "Windows 10 and 11. No separate VPN client needed."],
        ["Run the setup", "The tunnel driver installs itself, no reboot required."],
        ["Sign in", "The same login and password as in the dashboard."],
        ["Confirm the system prompt", "Windows asks for administrator rights once — for the network adapter and the tunnel service."],
        ["Press connect", "Fast path by default, the backup one kicks in on its own if the network blocks it. Split tunneling is a switch on the main screen."],
      ],
    },
    tv: {
      title: "Connecting on a TV",
      appTitle: "Prosto VPN for Android TV",
      appText: "The same file as for Android: no separate build. The interface adapts to the remote.",
      download: "Download APK",
      steps: [
        ["Download the APK on a computer", "The button above. Same file as for the phone."],
        ["Copy it to a USB stick", "Put the APK on a regular USB stick and plug it into the TV."],
        ["Install from the stick", "TV file manager → find the APK → install. Allow unknown sources if asked."],
        ["Sign in with login and password", "The same as in the dashboard. On-screen keyboard from the remote; case matters."],
        ["Confirm and connect", "The TV asks permission for the VPN — confirm and press connect. A nearby country usually gives the best speed."],
      ],
    },
  },

  features: {
    eyebrow: "WHAT'S INSIDE",
    title: "The app does the thinking",
    lead: "Everything that used to be set up by hand is now built in. Here's what happens under the button.",
    cards: [
      ["Two paths to every server", "A fast one over UDP and a backup over TCP that looks like an ordinary website. The network blocks the first — the app switches to the second and remembers it for that network."],
      ["Port cycling", "If a carrier throttles one port, the app tries others. You only see “Connecting…” and, half a minute later, “Connected”."],
      ["Banks outside the VPN", "On Android — per app: tick the bank and it goes direct. On Windows, Mac and via the address list — Russian networks bypass the tunnel with one switch."],
      ["Keys for iPhone and Happ", "The dashboard issues a vpn:// key for AmneziaVPN and a subscription link for Happ, Hiddify, Streisand. The link updates itself when we change something."],
      ["Devices under control", "Every sign-in is visible in the dashboard — device and time. An extra one is disconnected with one tap, the slot frees up at once."],
      ["Server status", "prostovpn.cc/status and the strip at the top of the dashboard: every country's liveness once a minute. All green but not connecting — it's your network, not the server."],
    ],
  },

  split: {
    eyebrow: "BANKS AND LOCAL SERVICES",
    title: "Familiar services keep working",
    lead1: "Russian banks, government portals, marketplaces and delivery dislike a foreign address. Split tunneling lets them go direct: they see your normal home address, while everything else goes through the VPN.",
    lead2: "On Android the sturdiest way is to exclude the bank app itself — “Apps outside VPN” in settings. Windows, Mac and Android also have the address list built in. The steps below are for AmneziaVPN on iPhone, where the list is imported by hand; in Happ Russian sites go direct out of the box.",
    fileButton: "Get the list in the dashboard",
    botButton: "Get it from the bot",
    steps: [
      ["Download the address list", "In the dashboard, “Keys” section, or in the bot — a file with Russian ranges."],
      ["Open split tunneling", "In AmneziaVPN the section lives in the connection settings."],
      ["Choose the list mode", "“Addresses from the list should not open through the VPN” — Russian networks go direct, the rest stays in the tunnel."],
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
    lead: "Five reasons that close almost every request",
    cards: [
      ["It won't connect", "Switch the country and try again. Mobile data instead of Wi-Fi often helps too: networks block VPN differently. And close other VPNs."],
      ["Check the servers", "Open prostovpn.cc/status. All green but only you can't connect — it's the carrier's network; message us and we'll say which country to pick."],
      ["Slow speed", "Pick another country — the nearest isn't always the fastest. Speed depends on node load more than on distance."],
      ["Banks don't open", "On Android tick the bank in “Apps outside VPN”. On other devices turn on split tunneling — Russian addresses go direct."],
      ["Drops in the background", "Huawei, Honor, Xiaomi unload the app from memory. Settings → “Background activity” — a one-time button. Notifications must stay on."],
    ],
    askTitle: "Still have questions?",
    askText: "Detailed answers are on the Questions & answers page. In Telegram and by email real people reply.",
    askBot: "Support in Telegram",
    askFaq: "Questions & answers",
  },
};
