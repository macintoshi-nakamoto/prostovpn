# Handoff: Prosto VPN — iOS App (Login + Connection)

## Overview
Prosto VPN is a dark-theme iPhone VPN client in the spirit of Amnezia VPN: a login screen and a main connection screen with server picker (draggable bottom sheet), settings (incl. split tunneling with tunneling-file management), and a support/about page. Modern minimalist style with Apple "liquid glass" elements (frosted translucent circular buttons) and Telegram-like native smoothness.

## About the Design Files
The files in this bundle are **design references created in HTML** — prototypes showing intended look and behavior, not production code to copy directly. The task is to **recreate these designs in the target codebase's environment** (SwiftUI / UIKit / Flutter / React Native — whatever the project uses; if nothing exists yet, SwiftUI is the natural choice for an iOS-only app) using its established patterns. The HTML files open directly in a browser and are fully interactive — use them as the behavioral spec.

## Fidelity
**High-fidelity (hifi).** Colors, typography, spacing, radii, and interactions are final. Recreate pixel-perfectly.

## Design Tokens

### Colors
- App background gradient: `#1a110b` → `#120c08` (180deg, top to bottom)
- Page glow accents: radial `rgba(255,80,0,.13)` blurred orbs (decorative, animated float)
- Primary gradient (buttons, active toggles): `linear-gradient(135deg, #FF711F, #FF4000)`
- Primary solid accents: `#FF5000` (base), `#FF6A1F` (links/accents), `#FF8A50` (icons/labels), `#FFB184` (hover)
- Accent tint fills: `rgba(255,80,0,.08)` / `.10` / `.12` / `.14` (cards, icon chips, selected rows)
- Text primary: `#eef2ff`
- Text secondary: `rgba(235,240,255,.4–.45)`
- Text tertiary/hints: `rgba(235,240,255,.28–.35)`
- Surfaces (cards/rows): `rgba(255,255,255,.03–.07)` with `inset 0 1px 0 rgba(255,255,255,.06)` top highlight
- Dividers: `rgba(255,255,255,.06)`, 1px
- Destructive (delete button): `linear-gradient(135deg,#ff3b30,#d92419)`
- Success (connected state ring/button "done"): `linear-gradient(135deg,#2ec27e,#27a06a)` on login; connect screen stays orange
- Error text: `#ff7a8a`-family red

### Liquid glass buttons (header circles: logo, settings gear, back arrow)
- 46×46 circle
- `background: linear-gradient(160deg, rgba(255,255,255,.12), rgba(255,255,255,.04) 55%)`
- `backdrop-filter: blur(20px) saturate(1.6)`
- `border: 1px solid rgba(255,255,255,.14)`
- `box-shadow: inset 0 1px 0 rgba(255,255,255,.22), inset 0 -1px 0 rgba(255,255,255,.05), 0 8px 24px rgba(0,0,0,.35)`
- Hover: brighter gradient + `scale(1.06)` (gear also rotates 30deg); press: `scale(.92)`
- Transition: `.25s cubic-bezier(.3,.9,.3,1)`

### Typography
- Font: **Manrope** (400/500/600/700/800), system-ui fallback
- Screen title (Настройки): 30px / 800
- Sheet title: 20px / 800
- Status text (Подключено): 24–26px / 800
- Row title: 15px / 700
- Row description: 12.5px / 500, secondary color
- Button label: 15–17px / 700
- Badges (AWG2): 11px / 700, letter-spacing .5px
- Small hints: 11.5–12px / 600

### Radii
- Cards/groups: 20px; rows: 14–16px; buttons: 15–18px; sheet top corners: 28px; icon chips: 10–13px; toggles: full pill

### Spacing
- Screen padding: 24–28px horizontal
- Card internal padding: 6px wrapper + 13px 10px rows
- Gaps: 12–14px between major blocks, 8–9px between buttons

### Toggle (switch)
- Track 48×29, radius 15, padding 2.5; ON: primary gradient, OFF: `rgba(255,255,255,.12)`
- Knob 24×24 white circle, shadow `0 2px 6px rgba(0,0,0,.35)`, slides 19px, `.25s cubic-bezier(.3,.9,.3,1)`

## Screens

### 1. Login (`Алиса VPN - Вход.dc.html`)
- Centered logo image (`assets/logo.png`, ~190px wide) with orange glow `drop-shadow(0 0 24px rgba(255,113,31,.35))`, app name "Prosto VPN" 28px/800, subtitle "Свободный и безопасный интернет" 14px/500 secondary.
- Two fields (Логин / Пароль) as bare rows (no card, no borders): icon 20px (user / padlock, 1.8px stroke) + input 16px/500. Focus state: row background `rgba(255,255,255,.05)`, radius 14px, no outline/border. Divider between rows.
- Password row has eye toggle (show/hide), 22px icon, secondary color, hover brightens.
- Primary button "Войти" — full width, 17px padding, radius 18px, primary gradient, shadow `0 8px 28px rgba(255,80,0,.35)`; hover `brightness(1.1)`, press `scale(.98)`. Loading state: "Подключение…" at 70% opacity (1.2s), then success "✓ Готово" in green gradient.
- Validation: empty login → "Введите логин"; password < 4 chars → "Пароль слишком короткий" (13px/600 red, above button).
- Footer: "Продолжая, вы принимаете условия сервиса" 12px tertiary, link slightly brighter.
- No "forgot password" / "create account" links.

### 2. Connection (`Алиса VPN - Подключение.dc.html`) — main screen
Header: liquid-glass logo button left (opens Support page; logo image centered, nudged 2px down, fills the circle), liquid-glass gear right (opens Settings).

Power button (center):
- 210px circle, `rgba(255,255,255,.05)` fill, `backdrop-filter: blur(24px)`, border 1.5px `rgba(255,255,255,.1)`; white power icon (74px, stroke 2).
- Connected: border `rgba(255,80,0,.8)`, glow `0 0 40px rgba(255,80,0,.25)`, pop-in animation `popIn .45s cubic-bezier(.3,.9,.3,1)` (scale .92 → 1.03 → 1).
- Connecting: a conic-gradient ring **traces the button's own border** (masked ring, 2.5px thick): `conic-gradient(transparent 10% → rgba(255,80,0,.15) 55% → #FF5000 100%)`, spinning 1.1s linear. No text during connecting. 1.6s then connected.
- Status: "Отключено" / "Подключение…" / "Подключено" 24px/800; subtext: "Нажмите, чтобы подключиться" or elapsed timer `MM:SS` ticking every second.

Server row (below status): card `rgba(255,255,255,.045)` radius 18, flag chip 40px in orange tint square, name "Нидерланды" 15px/700 + badge "AWG2", sub "Амстердам · 34 мс", chevron right. Tapping opens the bottom sheet.

Bottom sheet (server picker):
- Peeks from bottom; **opens by tap on the grab handle AND by dragging with a finger** (pointer events on the whole sheet; drag threshold ~40px or velocity; smooth spring `.45s cubic-bezier(.3,.9,.3,1)` snap; while dragging follows finger 1:1, clamped +120/−110px).
- Grab handle: 38×4px pill `rgba(255,255,255,.16)`.
- Header "ВЫБЕРИТЕ СЕРВЕР" 11px/700 letter-spaced tertiary.
- Servers: Нидерланды (Амстердам · 34 мс), Швеция (Стокгольм · 41 мс), Германия (Франкфурт · 48 мс) — each with flag chip, AWG2 badge, ping, orange check on active; selected row tinted `rgba(255,80,0,.1)`. Picking a server closes the sheet; dragging never triggers selection (drag guard).
- Sheet surface: `linear-gradient(180deg,#241710,#170f0a)`, top radius 28, `inset 0 1px 0 rgba(255,255,255,.08)`, big soft shadow; dimmed blurred backdrop when open (tap to close).

### 3. Settings (slides in over connection screen, `fadeUp .4s`)
Back: liquid-glass circle with single chevron (no text). Title "Настройки" 30px/800.

Group 1 (single card):
1. **Раздельное туннелирование** — toggle, desc "Обходит видимость VPN для РФ сервисов". Default ON.
   - When ON, a full-width primary-gradient button "**Добавить файл**" (with plus icon) appears under the row (hidden when OFF, no toggle-less states — the whole button block collapses).
   - Button opens the **tunneling-file bottom sheet** (see below).
2. **Kill Switch** — toggle ON, desc "Блокировать интернет при обрыве VPN"
3. **Автозапуск** — toggle OFF, desc "Запускать приложение при старте устройства"
4. **Автоподключение** — toggle OFF, desc "Подключаться к VPN при запуске"
5. **Логирование** — toggle ON, desc "Сохранять журнал для диагностики"

Group 2: **Язык** row — right side has a minimal segmented control (RU / EN pills in `rgba(255,255,255,.06)` container, active pill = primary gradient). Switching applies instantly to **all UI strings** (full i18n dictionaries in the prototype's logic, keys: settings/split/kill/autostart/autoconnect/logging/language/logout/back/fileTitle/fileDesc/chooseFile/del/holdHint/connected/connecting/disconnected/tapToConnect/chooseServer etc.).

Bottom: **Выйти из аккаунта** — full-width tinted red-orange button (`rgba(255,80,0,.08)`, text `#FF6A1F`).

Tunneling-file bottom sheet (slides up `sheetUp .35s cubic-bezier(.3,.9,.3,1)`, dim backdrop):
- Title "Файл туннелирования", desc: "Список сайтов и приложений, которые идут через VPN. Форматы: .json или .txt — по одному домену или названию приложения на строку."
- **File list** (scrollable, max ~230px): each row = file icon chip, name, meta line. Default entry pre-added: `default_list.json` — meta "По умолчанию · 214 записей", orange check = active.
- Multiple files: adding more (button "Выбрать файл", primary gradient, upload icon) appends `my_list_N.json`; tap a row to make it active (single active check).
- **Long-press a row (~550ms)** reveals a red "Удалить" button on that row (default file cannot be deleted). Deleting shifts active selection sensibly. Hint under list: "Удерживайте файл, чтобы удалить его".
- No "manually pick apps" button.

### 4. Support / About (opens from logo button, slides over)
- Liquid-glass back circle. Logo + "Prosto VPN" + "Версия 1.0.0".
- Card with rows (icon chip + title + sub + chevron):
  - Поддержка в Telegram — `@prosto_vpn_supp`
  - Наш сайт — `prostovpn.media`
  - Частые вопросы — "Как настроить и решить проблемы"
- Footer links: Политика конфиденциальности · Условия.

## Interactions & Behavior summary
- Connect: idle → connecting (1.6s, spinning border ring) → connected (timer starts). Tap again → disconnect (timer resets).
- Sheet drag: pointer down anywhere on sheet, move follows finger, release snaps open/closed by threshold; taps still work.
- Settings/Support pages: absolute overlays with `fadeUp` entrance; no tab bar.
- Language: instant re-render of all strings from RU/EN dictionaries.
- All press feedback: `scale(.92–.98)`; hovers brighten; every transition uses `cubic-bezier(.3,.9,.3,1)` (springy, Telegram-like).

## State Management
- `phase: off|connecting|on`, `secs` (timer, interval 1s)
- `server: index` (3 servers), `sheetOpen`, drag state (`dragging, dragY`)
- `page: main|settings|about`
- Settings: `split, kill, autoStart, autoConnect, logging` booleans
- Files: `files: [{name, count, def?}], activeFile, deleteIdx` (long-press state)
- `lang: ru|en`

## Assets
- `assets/logo.png` — white "P" emblem in circle (user-provided). Orange glow applied via drop-shadow in UI.
- Icons: inline SVG strokes (user, padlock, eye, power, gear, chevrons, upload, file, plus, telegram, globe, question) — 1.8–2.4px stroke, round caps.
- Flags: emoji (🇳🇱 🇸🇪 🇩🇪) in tinted chips.

## Files
- `Алиса VPN - Вход.dc.html` — login screen (interactive prototype)
- `Алиса VPN - Подключение.dc.html` — connection screen + settings + support + sheets (interactive prototype)
- `assets/logo.png` — logo
- `ios-frame.jsx` — iPhone bezel wrapper used by the prototypes (presentation only, not part of the design)

Note: prototypes are rendered inside an iPhone frame at 390×844 (iPhone 14/15 logical size). Status bar / home indicator come from the frame, not the design.
