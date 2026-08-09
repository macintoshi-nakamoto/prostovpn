# Prosto VPN — Windows

Десктопный клиент Prosto VPN на Compose Desktop: тот же дизайн и тот же
liquid glass, что в iOS/Android-клиентах (Skia исполняет тот же SkSL-шейдер
преломления). Компактное безрамочное окно 400×640 со скруглёнными углами,
перетаскиванием за любое пустое место и своими кнопками свернуть/закрыть.

Тестовая сборка: вход по ключу `vpn://…` (Амнезия) с определением сервера,
гостевой режим, подключение пока симулируется — точка интеграции реального
туннеля: `AppState.startConnect()`.

## Сборка

Установщик Windows (MSI + EXE) собирается на Windows (нужен JDK 17+):

```bat
cd windows
gradlew.bat packageMsi packageExe
```

Готовые файлы: `build/compose/binaries/main/msi/` и `.../exe/`.

Либо через GitHub Actions: workflow **windows-desktop** собирает установщики
на каждом пуше в `main`, затрагивающем `windows/` (артефакты — на странице
запуска workflow).

Запуск из исходников на любой ОС:

```
./gradlew run
```

## Скриншоты без дисплея

```
./gradlew screenshots
```

Рендерит все экраны в `screenshots/*.png` (проверка вёрстки и liquid glass).
