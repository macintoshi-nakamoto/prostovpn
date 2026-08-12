# Nexa VPN

<p align="center">
  <img src="branding/nexa-master-icon.png" alt="Иконка Nexa VPN" width="160">
</p>

Nexa VPN — кроссплатформенный GPL-3.0-клиент для VPN на собственном сервере. Это открытый форк [Amnezia VPN](https://github.com/amnezia-vpn/amnezia-client), зафиксированный на upstream-коммите [`e38a233904d9db148f620fdd30fd56a770b457e8`](https://github.com/amnezia-vpn/amnezia-client/commit/e38a233904d9db148f620fdd30fd56a770b457e8).

Сейчас репозиторий находится на стадии исходного проекта: это ещё не опубликованный VPN-сервис и не набор проверенных релизных сборок. Название, идентификаторы приложений, установщики и графика заменены на Nexa VPN. Коммерческие функции Amnezia и автоматические обновления по инфраструктуре upstream по умолчанию отключены, пока у Nexa нет собственного backend и канала подписанных обновлений.

[English](README.md)

## Что уже входит в проект

- Единый интерфейс Qt/QML для Windows, Linux, macOS, Android и iOS.
- Автоматическая установка личного VPN-сервера через SSH и Docker.
- Транспорты AmneziaWG/AWG2, WireGuard, OpenVPN, Xray VLESS + REALITY и SSXray.
- Клиент IKEv2/IPsec для Windows.
- Раздельное туннелирование, kill switch, настройка DNS, импорт/экспорт профилей и импорт QR-кодов.
- Оригинальная графика Nexa VPN и набор иконок для всех платформ.

`AmneziaWG` сохранён как техническое имя совместимого протокола. Старые профили `.vpn`, ссылки `vpn://`, сериализованные ключи и уже установленные контейнеры `amnezia-*` остаются совместимыми. Устаревшие Cloak и прямой Shadowsocks, встречающиеся в документации upstream, не заявляются как поддерживаемые транспорты.

## Состояние платформ

| Платформа | Что есть в исходниках | Что требуется для релиза |
| --- | --- | --- |
| Windows 10/11 | Клиент и привилегированная служба | Visual Studio/Qt; для публикации — сертификат Authenticode |
| Linux | Клиент и привилегированная служба | Qt/Conan и упаковка под нужные дистрибутивы |
| Android 9+ | Нативные backend-службы `VpnService` | JDK 17, Android SDK/NDK, Qt for Android и постоянный ключ подписи |
| macOS | Обычный desktop-режим или Network Extension | macOS/Xcode, Developer ID, provisioning и notarization |
| iPhone/iPad | Network Extension | Apple Developer Team, профили приложения/расширения и entitlement Network Extension |

Точный исходный upstream-коммит успешно проходил CI-сборку Windows, Linux, обычного macOS, Android и компиляцию iOS. Изменённое дерево Nexa ещё нужно собрать в чистых средах, подписать и проверить на реальных устройствах. Инструкции находятся в [docs/BUILDING.md](docs/BUILDING.md).

## Получение исходников

```bash
git clone --recurse-submodules <адрес-вашего-репозитория-nexa>
cd nexa-vpn
git submodule update --init --recursive
```

В текущем рабочем дереве исходный репозиторий сохранён под именем remote `upstream`. Перед распространением бинарных файлов укажите публичный адрес своего форка и сайта:

```bash
cmake -S . -B deploy/build \
  -DNEXA_SOURCE_URL=https://github.com/your-org/nexa-vpn \
  -DNEXA_HOMEPAGE_URL=https://your-project.example
```

Зависимости и команды сборки описаны в [docs/BUILDING.md](docs/BUILDING.md). Устройство проекта и границы совместимости — в [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) и [docs/UPSTREAM.md](docs/UPSTREAM.md).

## Безопасность

Текущую версию нельзя считать прошедшим аудит production-VPN. Автообновления upstream отключены, однако остаются приоритетные задачи: проверка SSH host key, безопасное шифрование резервных копий, хранилище секретов, защита привилегированного IPC и проверяемая цепочка сборки серверных образов. Перед работой с чувствительной инфраструктурой прочитайте [docs/SECURITY.md](docs/SECURITY.md).

## Лицензия и указание авторства

Nexa VPN распространяется по GPL-3.0, поскольку основан на Amnezia VPN. При каждой публикации необходимо сохранять [LICENSE](LICENSE), [NOTICE](NOTICE), доступ к соответствующим исходникам и лицензии сторонних компонентов. Имена `AmneziaWG`, сторонних библиотек и старых идентификаторов конфигурации не означают поддержку проекта со стороны команды Amnezia.

До публикации в магазинах выполните [release checklist](docs/RELEASE_CHECKLIST.md), включая проверку названия и товарного знака: в Google Play уже существует другое приложение с публичным названием «Nexa VPN».
