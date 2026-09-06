/* English FAQ — same structure as faq.ru.js, same keys per block. */
export const faqEn = {
  eyebrow: "Help",
  title: "Questions & answers",
  lead: "Everything people ask support — from the first sign-in to the fine print. Start typing what happened.",
  search: "What happened? E.g. won't connect, iPhone, pause…",
  empty: "Nothing matches — message us, we'll answer and add it here.",
  allTopics: "All topics",
  notFound: "Didn't find the answer?",
  write: "Message support",
  blocks: [
    {
      key: "start",
      h: "Getting started",
      items: [
        [
          "What does Prosto VPN open?",
          "Everything that stopped opening: video, social networks, messengers, games and ordinary sites. Tap “Connect” and use them as before, no setup. You decide what to watch. Banks, marketplaces and government services keep working directly — they never go through the VPN.",
        ],
        [
          "I've paid. What now?",
          "Download the app for your device and sign in with the same login and password as in the dashboard. The app takes the rest from your account: countries, keys, settings — nothing to paste. On iPhone there's no app of ours: connect through AmneziaVPN or Happ with a key from the dashboard, section “Keys”.",
        ],
        [
          "Can I try it for free?",
          "Yes. Signing up opens a two-day trial with 15 GB on one device. No card, nothing is charged. Liked it — pick a plan in the dashboard, the same account continues.",
        ],
        [
          "Where do I download the app?",
          "Dashboard → “Download the app”: choose the device and get the link. Android and TV share one APK from the site, no Google Play needed. Windows — an installer, Mac — a .dmg image. The same links are in the Telegram bot.",
        ],
        [
          "What is the dashboard for?",
          "prostovpn.cc/account — subscription, payments, devices, iPhone keys, friends and settings. It also opens inside the Telegram bot as a mini app — the same thing, without a password.",
        ],
        [
          "I signed up via Telegram. What are my login and password?",
          "They were shown once right after sign-up. Didn't save them — in the dashboard (inside Telegram) open the profile → “Sign-in on the site and in apps”: your login and a new password are there.",
        ],
      ],
    },
    {
      key: "devices",
      h: "Devices and the limit",
      items: [
        [
          "How many devices can I use?",
          "As many as the plan includes — the number is on its card. Counted: app sign-ins (one per device), iPhone keys that have been used, and links for Happ and similar apps. A computer and a phone work at the same time.",
        ],
        [
          "What if I sign in from one device too many?",
          "Signing in isn't blocked: the oldest app session is disconnected, and signing in again there is enough. A new iPhone key or Happ link beyond the limit, though, won't be issued — free a slot in “Devices” first.",
        ],
        [
          "How do I disconnect a device I no longer use?",
          "Dashboard → “Devices”: tap the row and confirm. The slot frees up immediately. iPhone keys are disconnected in “Keys” the same way.",
        ],
        [
          "Can I share my access with a friend?",
          "Better not. One key on many devices is visible, and we contact the owner. There's an honest way: invite them with the link from “Friends” — you both get days as a gift.",
        ],
      ],
    },
    {
      key: "connect",
      h: "Connecting",
      items: [
        [
          "Where can I see what's being blocked right now?",
          "On the blocking map: prostovpn.cc/blocks. For every carrier — MTS, Beeline, MegaFon, Tele2, home providers — it shows which connection methods work right now and what changed in the last 24 hours. Live data from our own apps, no addresses or personal data. If one method is down on your carrier and another works, switch to it in the app.",
        ],
        [
          "It won't connect. What do I do?",
          "In order: close other VPNs; try another country; switch between Wi-Fi and mobile data — networks block VPN differently. Our app cycles ports and the backup path on its own, give it half a minute. If everything is green on prostovpn.cc/status and only you can't connect, it's your carrier's network — message us and we'll say what to pick.",
        ],
        [
          "Connected, but sites don't open",
          "Try another country — sometimes a specific node is blocked on your carrier only. If it says “via backup path” under “Connected”, that's fine: the app switched to the second method, speed may differ.",
        ],
        [
          "How do I check the VPN really works?",
          "Open any site that shows your IP address — the country must match the one in the app. On the app's main screen the received/sent counters grow while the tunnel is alive.",
        ],
        [
          "What does “via backup path” mean?",
          "Every server has two ways in. The main one is fast, over UDP. If the network doesn't let it through (common on mobile and in some offices), the app switches to the second one, over TCP, which looks like an ordinary website. Nothing to do.",
        ],
        [
          "Slow speed",
          "Switch the country: the nearest isn't always the fastest, speed depends on node load more than on distance. On mobile data, Wi-Fi helps. And check no other VPN runs in parallel.",
        ],
        [
          "What does the server status page show?",
          "prostovpn.cc/status — liveness of every country, refreshed every minute. The same strip sits at the top of the dashboard. If it's fine there but not for you, the problem is between you and the server, not on it.",
        ],
        [
          "Which countries are there?",
          "The list is always current in the app and on the status page. Europe for now; nodes are added as demand grows.",
        ],
      ],
    },
    {
      key: "split",
      h: "Banks and local services",
      items: [
        [
          "A bank or government app fails with the VPN on",
          "Turn on split tunneling in the app settings: Russian addresses go direct and the services see your normal home address. On Android there's a sturdier way — let the bank app itself bypass the VPN (next question).",
        ],
        [
          "How do I let one app bypass the VPN on Android?",
          "Settings → “Apps outside VPN” → tick the bank, government app, delivery — anything. Their traffic goes direct wherever they connect, the rest stays in the tunnel. Sturdier than an address list: banks move to clouds and lists lag behind.",
        ],
        [
          "What is split tunneling?",
          "A mode where not everything goes through the VPN — only what needs it. Ours works by a list of Russian addresses: they go direct. In the Windows, Mac and Android apps the list is built in — just flip the switch.",
        ],
        [
          "And on iPhone?",
          "In AmneziaVPN the list is imported by hand: download the file in the dashboard (“Keys”) and add it under “Split tunneling” in the connection settings — step by step in the guide. In Happ Russian sites go direct out of the box.",
        ],
        [
          "Split tunneling is on but the bank still fails",
          "The address list sometimes lags: the bank opened new servers. On Android tick the bank app in “Apps outside VPN”. On other devices send us the bank's name — we'll add its addresses, the update ships with the app.",
        ],
      ],
    },
    {
      key: "iphone",
      h: "iPhone and other apps",
      items: [
        [
          "Is there an iPhone app?",
          "Not yet. Connect through free apps: AmneziaVPN (a key from the dashboard) or Happ (a link from the dashboard). Both are in the App Store. Our key works the same in both.",
        ],
        [
          "AmneziaVPN isn't in the App Store",
          "With a Russian Apple ID the app doesn't show in search. Fixed in a couple of minutes by changing the store region — two ways with screenshots in the guide, “iPhone” tab. iCloud, photos and notes are not affected.",
        ],
        [
          "Where do I get the iPhone key?",
          "Dashboard → “Keys” → “Add key”: pick a country and get a vpn://… string and a QR code. Paste the string into AmneziaVPN on the Connection screen, Insert key. One key — one country; want another — add another key.",
        ],
        [
          "What is a Happ link and how is it different from a key?",
          "A subscription link: paste it once and the app gets all countries and the best server on its own, updating itself when we change something. An AmneziaVPN key is one country for good. For iPhone we recommend Happ: Russian sites direct and the backup path are already set up there.",
        ],
        [
          "Which other apps work?",
          "With the dashboard link: Happ, Hiddify, Streisand, v2rayNG and other apps that support subscriptions. With a vpn:// key: AmneziaVPN 5.0 or newer. On Android, Windows, Mac and TV our own app is better: everything is on by default.",
        ],
        [
          "The key stopped working after a pause or renewal",
          "It shouldn't: keys and links survive pauses and renewals, no need to replace them. If the app reports an error, update it and try again. Still stuck — message us, we'll check by key number.",
        ],
      ],
    },
    {
      key: "plan",
      h: "Subscription and payment",
      items: [
        [
          "How do I pay?",
          "Dashboard, “Subscription” tab: choose a plan and a method. We accept SBP, Telegram Stars, crypto and TON. Days are added right after payment, nothing to enter.",
        ],
        [
          "How do I renew?",
          "Same as paying: days are added to the current ones, nothing burns. Three days before the end the app shows a reminder and a renew button.",
        ],
        [
          "Is there auto-renewal?",
          "Only if you enabled it yourself in the dashboard. It's switched off there with one button, no emails or calls. Without your action we charge nothing.",
        ],
        [
          "What happens when the subscription ends?",
          "The country list in the app goes empty and the connection drops. The account and keys stay yours: after payment everything comes back, nothing to re-enter.",
        ],
        [
          "What happens when the traffic runs out?",
          "On plans with a traffic cap access closes the same way as without payment. The app warns in advance — under 5 GB left it shows the remainder and a renew button. The counter resets with renewal.",
        ],
        [
          "Can I pause the subscription?",
          "Yes, on a paid plan: dashboard → home → “Pause”. Days stop ticking until you press “Resume”. At most twice per calendar month; after 180 days the pause lifts itself. No pause on trial or gift days.",
        ],
        [
          "Can I give days to someone else?",
          "Yes: dashboard → “Subscription” → “Transfer days”. Enter the recipient's public ID (in their profile, PV-XXXX-XXXX) and the number of days. Transfers are final, so the dashboard asks to confirm.",
        ],
        [
          "How do I get days for free?",
          "“Friends” section: you have a link. A friend signs up through it — you both get gift days, the amount is shown there. Sometimes we give days via promo links in the channel — they're added as a gift and don't interfere with pauses.",
        ],
        [
          "Can I get a refund?",
          "Message support describing what didn't fit. We look at each case; the rules are on the “Refunds” page.",
        ],
      ],
    },
    {
      key: "account",
      h: "Account and security",
      items: [
        [
          "Forgot my password",
          "If an email is attached to the account — press “Forgot password?” on the sign-in page, a reset link arrives. No email but Telegram — open the dashboard in the bot and set a new password in the profile. Neither — message support, we'll confirm ownership and issue a new one.",
        ],
        [
          "How do I change the password?",
          "Dashboard → profile → “Change password”. Sessions on other devices stay; to kick a stranger, go to “Devices”.",
        ],
        [
          "Why attach email and Telegram?",
          "Email — to recover the password without writing to support. Telegram — so the dashboard opens in the bot without a password and important subscription messages reach you. Neither is mandatory.",
        ],
        [
          "How do I link Telegram to an existing account?",
          "Open the dashboard inside the bot and sign in with login and password once — from then on the account is linked and opens without a password.",
        ],
        [
          "What do you store about me?",
          "Login, hashed password, subscription term, payments, sign-ins (device and time) and total traffic per period. No browsing history — there's nowhere to keep it: nodes run in RAM. Details on the “Privacy” page.",
        ],
        [
          "I got a message that my key is used on several devices",
          "It means more addresses sit on one key at once than the plan allows, and for longer than a couple of minutes. Family at home plus a phone on the road is normal. If the key leaked — disconnect it in “Keys” and issue a new one, the old one stops working.",
        ],
      ],
    },
    {
      key: "apps",
      h: "Apps",
      items: [
        [
          "Mac: “the developer cannot be verified”",
          "That's how macOS greets any app outside the App Store without Apple notarization — it's not malware and nothing is broken. Click OK, open System Settings → Privacy & Security, scroll down: there's a line about ProstoVPN with an “Open Anyway” button — click it and confirm with your password. On macOS 15 it may ask twice: first about the .dmg, then about the app itself. On macOS 14 and older, right-click the app → Open is enough. Terminal fans: xattr -dr com.apple.quarantine /Applications/ProstoVPN.app. It's a one-time thing; updates install without questions afterwards.",
        ],
        [
          "How do I update the app?",
          "It updates itself. When a new version is out, an “Update” button appears in settings — the app downloads the file, checks the signature and restarts as the new one. Android asks for install permission once.",
        ],
        [
          "Android: the file downloaded as .bin",
          "Older versions of the site did that. Download again — it now arrives as .apk. If the file is already in Downloads, rename it to .apk and install, it's intact.",
        ],
        [
          "Android: the app drops in the background",
          "Huawei, Honor, Xiaomi and similar skins unload apps from memory. Settings → “Background activity” — a button there lifts the restriction; it's a one-time action. And keep notifications on: without them the system doesn't see the VPN running.",
        ],
        [
          "Windows asks for administrator rights",
          "Once, on the first connection: the app installs a network adapter and a tunnel service, which a regular user can't. It won't ask again.",
        ],
        [
          "Mac asks for a password",
          "Same thing — once, to raise the tunnel. The password stays on your computer, it never reaches us.",
        ],
        [
          "How do I install on a TV?",
          "Download the APK on a computer, copy it to a USB stick, install through the TV's file manager and sign in with login and password. Step by step, with the on-screen keyboard and remote, in the guide, “TV” tab.",
        ],
        [
          "How do I remove ads?",
          "Dashboard → profile → “Ad blocking”, or in the app: Settings → “Ad blocking”. Ads and trackers are cut on our servers using a large daily-updated list; sites and apps keep working as usual. Applies on the next connection. The iPhone key carries the setting inside — re-issue it after turning this on.",
        ],
        [
          "What is auto-connect?",
          "Settings → “Start with the system”: the app connects on its own when the phone or computer starts. On Android you can also enable the system Always-on VPN — then no internet flows without the tunnel.",
        ],
        [
          "The app says “Connection dropped”",
          "The network changed or the node didn't answer several times in a row. The app reconnects on its own, usually within seconds; if not — try another country. Constant drops on one network — message us with the carrier's name.",
        ],
      ],
    },
    {
      key: "support",
      h: "Support",
      items: [
        [
          "Where do I write?",
          "Telegram: @temnoz — we answer within minutes on average. Or support@prostovpn.cc if messengers are inconvenient.",
        ],
        [
          "What to attach so it's fixed faster?",
          "Your public ID from the profile (PV-XXXX-XXXX), the device and carrier, and what the app says on screen — it names the reason in words. A screenshot beats a retelling.",
        ],
      ],
    },
  ],
};
