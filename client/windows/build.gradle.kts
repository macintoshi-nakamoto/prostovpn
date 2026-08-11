import org.jetbrains.compose.desktop.application.dsl.TargetFormat
import java.io.File
import java.net.URI
import java.security.MessageDigest
import java.util.zip.ZipFile

plugins {
    kotlin("jvm") version "2.2.20"
    id("org.jetbrains.compose") version "1.8.2"
    id("org.jetbrains.kotlin.plugin.compose") version "2.2.20"
}

dependencies {
    implementation(compose.desktop.currentOs)
    implementation(compose.material3)
    implementation("org.json:json:20240303")
    // Dispatchers.Main на десктопе живёт здесь: без этой зависимости
    // ServiceLoader не находит фабрику и любой переход на главный поток
    // падает окном «Module with the Main dispatcher is missing».
    // Версия должна совпадать с kotlinx-coroutines-core из Compose.
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-swing:1.8.0")
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

/**
 * Кладём сюда движок туннеля (prostovpn-tunnel.exe + wintun.dll) — jpackage
 * копирует содержимое в <install>\app\, приложение находит его там.
 * Движок собирается из windows/tunnel, wintun скачивается; в репозиторий
 * ни то, ни другое не коммитится.
 */
val tunnelResourcesDir = layout.projectDirectory.dir("resources/windows")

/**
 * Версия приложения.
 *
 * Задана явно в gradle.properties и растёт руками. Раньше третье поле
 * считалось числом коммитов в истории — и это молча сломало обновления:
 * историю свернули в один коммит, сборка стала называть себя 1.0.1, а у
 * людей уже стояла 1.0.16. Панель сравнивает версии по числам, честно
 * отвечала «установлена последняя», и кнопка обновления не появлялась
 * вообще — при том, что новая сборка была выложена.
 *
 * На сборке переопределяется: `-PappVersion=1.0.18` или PROSTO_VERSION.
 */
val appVersion: String = ((project.findProperty("appVersion") as String?)
    ?: System.getenv("PROSTO_VERSION")
    ?: project.findProperty("prostoVersion") as String?
    ?: error("не задана версия приложения: prostoVersion в gradle.properties")).trim()

/*
 * Проверяем здесь, а не после сборки установщика: WiX на неверной версии
 * падает сообщением про ProductVersion, по которому неочевидно, что дело
 * в одном числе из gradle.properties. Пределы — те, что разрешает MSI.
 */
run {
    val parts = appVersion.split(".")
    val limits = listOf(255, 255, 65535)
    check(parts.size == 3 && parts.withIndex().all { (i, p) ->
        p.toIntOrNull()?.let { it in 0..limits[i] } == true
    }) {
        "версия «$appVersion» не годится для MSI: нужны три числа, " +
            "major 0..255, minor 0..255, build 0..65535"
    }
}

/*
 * Версия и адрес панели, доступные из кода.
 *
 * В десктопном проекте нет BuildConfig — это понятие Android. Генерируем
 * крошечный файл на этапе сборки, иначе версию пришлось бы держать
 * строкой в двух местах, и она разъезжалась бы с установщиком.
 */
// Адрес панели задаётся сборкой и в репозитории не хранится: он
// принадлежит конкретной установке, а не коду.
//
//   ./gradlew packageMsi -PpanelUrl=https://панель.ваш-домен
//
// Обязательно домен, а не голый IP: на IP публичный сертификат не
// выпускается, а с самоподписанным клиент обрывает соединение до запроса —
// вход молча не проходит, и человек видит «ввожу логин и пароль, ничего не
// работает». Значение по умолчанию заведомо нерабочее, чтобы забытый
// параметр сборки было видно сразу, а не после выкладки.
val panelUrl: String = (project.findProperty("panelUrl") as String?)
    ?: System.getenv("PANEL_URL")
    ?: "https://panel.example.com"

val generateBuildInfo = tasks.register("generateBuildInfo") {
    val outputDir = layout.buildDirectory.dir("generated/buildinfo")
    val version = appVersion
    val url = panelUrl
    // Версия и адрес — входные данные задачи. Без этого Gradle считает её
    // выполненной и не перегенерирует файл при смене номера сборки: пакет
    // получает новый номер, а приложение продолжает считать себя старым и
    // предлагает обновиться само на себя без конца.
    inputs.property("version", version)
    inputs.property("panelUrl", url)
    outputs.dir(outputDir)
    doLast {
        val dir = outputDir.get().asFile.resolve("com/prostovpn/desktop")
        dir.mkdirs()
        dir.resolve("BuildInfo.kt").writeText(
            """
            package com.prostovpn.desktop

            /** Создаётся сборкой. Руками не править. */
            object BuildInfo {
                const val VERSION = "$version"
                const val PANEL_URL = "$url"
            }
            """.trimIndent() + System.lineSeparator()
        )
    }
}

kotlin.sourceSets["main"].kotlin.srcDir(generateBuildInfo)

compose.desktop {
    application {
        mainClass = "com.prostovpn.desktop.MainKt"

        nativeDistributions {
            appResourcesRootDir.set(layout.projectDirectory.dir("resources"))
            targetFormats(TargetFormat.Msi, TargetFormat.Exe)
            packageName = "Prosto VPN"
            // Та же версия, что видит приложение: MSI отказывается ставиться
            // поверх той же версии («Another version is already installed»),
            // а с большей версией штатно обновляет установленную.
            packageVersion = appVersion
            // Только ASCII: WiX собирает MSI в кодовой странице 1252,
            // кириллица в метаданных валит light.exe с ошибкой LGHT0311
            description = "Prosto VPN - free and secure internet"
            vendor = "Prosto VPN"

            windows {
                iconFile.set(project.file("packaging/icon.ico"))
                menuGroup = "Prosto VPN"
                shortcut = true
                dirChooser = true
                upgradeUuid = "6f2b1a44-7c1e-4b1d-9a55-0e3d0a7b52c1"
            }
        }
    }
}

// Рендер экранов в PNG без дисплея — для проверки вёрстки и liquid glass
tasks.register<JavaExec>("screenshots") {
    group = "verification"
    classpath = sourceSets["main"].runtimeClasspath
    mainClass.set("com.prostovpn.desktop.DevScreenshotKt")
    systemProperty("java.awt.headless", "true")
    systemProperty("skiko.renderApi", "SOFTWARE")
}

/**
 * Собирает наш движок туннеля из windows/tunnel.
 *
 * Это отдельный исполняемый файл: JVM не умеет ни поднимать драйвер Wintun,
 * ни работать службой Windows. Нужен Go 1.24+ на PATH.
 */
tasks.register<Exec>("buildTunnel") {
    group = "distribution"
    description = "Собирает prostovpn-tunnel.exe в resources/windows"

    val tunnelDir = layout.projectDirectory.dir("tunnel")
    val output = tunnelResourcesDir.file("prostovpn-tunnel.exe").asFile

    inputs.dir(tunnelDir)
    outputs.file(output)

    workingDir = tunnelDir.asFile
    environment("GOOS", "windows")
    environment("GOARCH", "amd64")
    environment("CGO_ENABLED", "0")
    // -H=windowsgui: движок вызывается из приложения, консольное окно
    // мелькать не должно; -trimpath убирает пути сборки из бинаря.
    commandLine(
        "go", "build",
        "-ldflags", "-s -w -H=windowsgui",
        "-trimpath",
        "-o", output.absolutePath,
        ".",
    )

    doFirst { output.parentFile.mkdirs() }
}

/**
 * Скачивает драйвер Wintun — движок туннеля грузит его из своего каталога.
 * В репозитории не хранится, контрольная сумма проверяется перед упаковкой.
 */
tasks.register("fetchWintun") {
    group = "distribution"
    description = "Скачивает wintun.dll в resources/windows"

    val outDir = tunnelResourcesDir.asFile
    val target = File(outDir, "wintun.dll")
    outputs.file(target)

    doLast {
        outDir.mkdirs()

        val wintunZipUrl = "https://www.wintun.net/builds/wintun-0.14.1.zip"
        val expectedSha = "e5da8447dc2c320edc0fc52fa01885c103de8c118481f683643cacc3220dafce"

        val tmp = File(outDir, "tmp").apply { mkdirs() }
        val wintunZip = File(tmp, "wintun.zip")

        logger.lifecycle("Скачиваю $wintunZipUrl")
        URI(wintunZipUrl).toURL().openStream().use { input ->
            wintunZip.outputStream().use { output -> input.copyTo(output) }
        }

        // в архиве несколько архитектур — берём amd64
        ZipFile(wintunZip).use { archive ->
            val entry = archive.entries().asSequence()
                .firstOrNull { !it.isDirectory && it.name.replace('\\', '/').endsWith("bin/amd64/wintun.dll") }
                ?: error("В $wintunZip нет bin/amd64/wintun.dll")
            archive.getInputStream(entry).use { input ->
                target.outputStream().use { output -> input.copyTo(output) }
            }
        }

        // В установщик уходит чужой бинарь, поэтому его подмену ловим
        // до сборки, а не после.
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(target.readBytes())
            .joinToString("") { "%02x".format(it) }
        check(digest == expectedSha) {
            "Контрольная сумма wintun.dll не совпала:\n  ожидали $expectedSha\n  получили $digest"
        }
        logger.lifecycle("wintun.dll: контрольная сумма совпала")

        tmp.deleteRecursively()
        // Остатки прежней поставки: движок Amnezia больше не используется
        File(outDir, "amneziawg.exe").delete()
    }
}

// Движок туннеля должен лежать в resources/windows до того, как Compose
// соберёт ресурсы приложения: prepareAppResources читает этот каталог,
// и без явной связи Gradle отказывается собирать (implicit dependency).
listOf(
    "prepareAppResources",
    "packageMsi",
    "packageExe",
    "packageDistributionForCurrentOS",
    "createDistributable",
    "runDistributable",
).forEach { name ->
    tasks.matching { it.name == name }.configureEach {
        dependsOn("buildTunnel", "fetchWintun")
    }
}

tasks.register<JavaExec>("keycheck") {
    group = "verification"
    classpath = sourceSets["main"].runtimeClasspath
    mainClass.set("com.prostovpn.desktop.KeyParserCheckKt")
}

tasks.register<JavaExec>("splitStats") {
    group = "verification"
    classpath = sourceSets["main"].runtimeClasspath
    mainClass.set("com.prostovpn.desktop.DevSplitStatsKt")
}

/**
 * Прогон ключа через путь приложения: gradlew keyprobe --args="<файл с ключом>".
 * Ключ читается из файла и в репозиторий не попадает.
 */
tasks.register<JavaExec>("keyprobe") {
    group = "verification"
    classpath = sourceSets["main"].runtimeClasspath
    mainClass.set("com.prostovpn.desktop.DevKeyProbeKt")
}

tasks.register<JavaExec>("panelcheck") {
    group = "verification"
    description = "Проверяет вход в панель без запуска окна"
    mainClass.set("com.prostovpn.desktop.PanelCheck")
    classpath = sourceSets["main"].runtimeClasspath
    args = listOf(
        (project.findProperty("panel") as String?) ?: panelUrl,
        (project.findProperty("login") as String?) ?: "",
        (project.findProperty("pass") as String?) ?: "",
    )
}
