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
 * Кладём сюда движок туннеля (amneziawg.exe + wintun.dll) — jpackage
 * копирует содержимое в <install>\app\, приложение находит его там.
 * Скачивается задачей fetchTunnelBinaries, в репозиторий не коммитится.
 */
val tunnelResourcesDir = layout.projectDirectory.dir("resources/windows")

compose.desktop {
    application {
        mainClass = "com.prostovpn.desktop.MainKt"

        nativeDistributions {
            appResourcesRootDir.set(layout.projectDirectory.dir("resources"))
            targetFormats(TargetFormat.Msi, TargetFormat.Exe)
            packageName = "Prosto VPN"
            packageVersion = "1.0.0"
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
 * Скачивает движок туннеля AmneziaWG (MIT) и Wintun для сборки установщика.
 * Бинарники не хранятся в репозитории — их тянет CI перед packageMsi.
 */
tasks.register("fetchTunnelBinaries") {
    group = "distribution"
    description = "Скачивает amneziawg.exe и wintun.dll в resources/windows"

    val outDir = tunnelResourcesDir.asFile
    outputs.dir(outDir)

    doLast {
        outDir.mkdirs()

        val awgZipUrl = "https://github.com/spvkgn/amneziawg-windows-client/releases/download/2.0.0-win7/amneziawg-amd64.zip"
        val wintunZipUrl = "https://www.wintun.net/builds/wintun-0.14.1.zip"

        // Контрольные суммы распакованных файлов: в установщик уходит чужой
        // бинарь, поэтому его подмену ловим до сборки, а не после.
        val expectedSha = mapOf(
            "amneziawg.exe" to "75392f89bc52cd04ae0a4c313ecd9f5c8a8d479baa40853b277bb252a106235b",
            "wintun.dll" to "e5da8447dc2c320edc0fc52fa01885c103de8c118481f683643cacc3220dafce",
        )

        fun verify(file: File) {
            val expected = expectedSha[file.name] ?: return
            val digest = MessageDigest.getInstance("SHA-256")
                .digest(file.readBytes())
                .joinToString("") { "%02x".format(it) }
            check(digest == expected) {
                "Контрольная сумма ${file.name} не совпала:\n  ожидали $expected\n  получили $digest"
            }
            logger.lifecycle("${file.name}: контрольная сумма совпала")
        }

        fun download(url: String, target: File) {
            logger.lifecycle("Скачиваю $url")
            URI(url).toURL().openStream().use { input ->
                target.outputStream().use { output -> input.copyTo(output) }
            }
        }

        fun extract(zip: File, entrySuffix: String, target: File) {
            ZipFile(zip).use { archive ->
                val entry = archive.entries().asSequence()
                    .firstOrNull { !it.isDirectory && it.name.endsWith(entrySuffix, ignoreCase = true) }
                    ?: error("В $zip нет $entrySuffix")
                archive.getInputStream(entry).use { input ->
                    target.outputStream().use { output -> input.copyTo(output) }
                }
            }
            logger.lifecycle("Распаковал ${target.name} (${target.length()} байт)")
        }

        val tmp = File(outDir, "tmp").apply { mkdirs() }

        val awgZip = File(tmp, "amneziawg.zip")
        download(awgZipUrl, awgZip)
        extract(awgZip, "amneziawg.exe", File(outDir, "amneziawg.exe"))
        verify(File(outDir, "amneziawg.exe"))

        val wintunZip = File(tmp, "wintun.zip")
        download(wintunZipUrl, wintunZip)
        // в архиве несколько архитектур — берём amd64
        ZipFile(wintunZip).use { archive ->
            val entry = archive.entries().asSequence()
                .firstOrNull { !it.isDirectory && it.name.replace('\\', '/').endsWith("bin/amd64/wintun.dll") }
                ?: error("В $wintunZip нет bin/amd64/wintun.dll")
            archive.getInputStream(entry).use { input ->
                File(outDir, "wintun.dll").outputStream().use { output -> input.copyTo(output) }
            }
        }
        logger.lifecycle("Распаковал wintun.dll")
        verify(File(outDir, "wintun.dll"))

        tmp.deleteRecursively()
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
        dependsOn("fetchTunnelBinaries")
    }
}

tasks.register<JavaExec>("keycheck") {
    group = "verification"
    classpath = sourceSets["main"].runtimeClasspath
    mainClass.set("com.prostovpn.desktop.KeyParserCheckKt")
}
