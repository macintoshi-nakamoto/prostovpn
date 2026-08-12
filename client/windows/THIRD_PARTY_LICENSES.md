# Сторонние компоненты в составе Prosto VPN для Windows

Движок туннеля `prostovpn-tunnel.exe` — наш собственный: исходники лежат
в `windows/tunnel`, установщик собирает его из них. Готовых чужих сборок
в поставке нет; единственный скачиваемый бинарь — драйвер Wintun.

## Движок туннеля — `prostovpn-tunnel.exe`

Собственная сборка. Внутри статически слинкованы MIT-компоненты:

- **amneziawg-go** — реализация протокола AmneziaWG,
  https://github.com/amnezia-vpn/amneziawg-go
- обвязка службы Windows, настройка адресов, маршрутов, DNS и правил
  брандмауэра — доработанный код `wireguard-windows` /
  `amneziawg-windows` (каталог `windows/tunnel/internal`,
  https://github.com/amnezia-vpn/amneziawg-windows). Изменения: свои имена
  службы (`ProstoVPNTunnel$…`), каналов и каталога данных, свой запуск,
  остановка без повышения прав и выгрузка журнала для приложения.

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
с WireGuard LLC и не аффилирован с проектом Amnezia — используется только
их код под лицензией MIT.

## Шрифты

- **Manrope** — SIL Open Font License 1.1, https://github.com/sharanda/manrope
- **Twemoji Mozilla** — Creative Commons Attribution 4.0 (графика Twemoji,
  © Twitter, Inc и другие участники), https://github.com/mozilla/twemoji-colr
