# Сторонние компоненты в составе Prosto VPN для Windows

Установщик содержит бинарные компоненты, необходимые для работы VPN-туннеля.
Оба скачиваются при сборке задачей `fetchTunnelBinaries` с проверкой SHA-256.

## AmneziaWG для Windows — `amneziawg.exe`

Клиент AmneziaWG (форк wireguard-windows), лицензия MIT.

- Исходники: https://github.com/amnezia-vpn/amneziawg-windows-client
- Сборка, которую мы кладём: https://github.com/spvkgn/amneziawg-windows-client
- SHA-256: `75392f89bc52cd04ae0a4c313ecd9f5c8a8d479baa40853b277bb252a106235b`

```
SPDX-License-Identifier: MIT

Copyright (C) 2015-2022 Jason A. Donenfeld <Jason@zx2c4.com>. All Rights Reserved.
Copyright (C) 2019-2021 WireGuard LLC. All Rights Reserved.

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## Wintun — `wintun.dll`

Драйвер сетевого адаптера для Windows, версия 0.14.1.
Готовые подписанные DLL распространяются по отдельной разрешительной лицензии
(«Prebuilt Binaries License»), не по GPL, которой покрыты исходники.

- Сайт и лицензия: https://www.wintun.net/
- SHA-256: `e5da8447dc2c320edc0fc52fa01885c103de8c118481f683643cacc3220dafce`

Wintun является товарным знаком WireGuard LLC. Prosto VPN не связан
с WireGuard LLC и не аффилирован с проектом Amnezia.

## Шрифты

- **Manrope** — SIL Open Font License 1.1, https://github.com/sharanda/manrope
- **Twemoji Mozilla** — Creative Commons Attribution 4.0 (графика Twemoji,
  © Twitter, Inc и другие участники), https://github.com/mozilla/twemoji-colr
