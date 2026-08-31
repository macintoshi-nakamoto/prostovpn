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

val tunnelResourcesDir = layout.projectDirectory.dir("resources/windows")

val appVersion: String = ((project.findProperty("appVersion") as String?)
    ?: System.getenv("PROSTO_VERSION")
    ?: project.findProperty("prostoVersion") as String?
    ?: error("не задана версия приложения: prostoVersion в gradle.properties")).trim()

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

val panelUrl: String = (project.findProperty("panelUrl") as String?)
    ?: System.getenv("PANEL_URL")
    ?: "https://panel.example.com"

gradle.taskGraph.whenReady {
    val packaging = allTasks.any { it.name.startsWith("package") && it.project == project }
    if (packaging && panelUrl == "https://panel.example.com") {
        throw GradleException(
            "Установщик собирается без адреса панели: он уйдёт людям с зашитым " +
                "panel.example.com, и приложение не сможет ни войти, ни обновиться. " +
                "Соберите так: ./gradlew packageMsi -PpanelUrl=https://ваш-домен"
        )
    }
}

val generateBuildInfo = tasks.register("generateBuildInfo") {
    val outputDir = layout.buildDirectory.dir("generated/buildinfo")
    val version = appVersion
    val url = panelUrl

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

        (project.findProperty("packagingJdk") as String?)?.let { javaHome = it }

        nativeDistributions {
            appResourcesRootDir.set(layout.projectDirectory.dir("resources"))
            targetFormats(TargetFormat.Msi, TargetFormat.Exe)
            packageName = "Prosto VPN"

            packageVersion = appVersion

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

tasks.register<JavaExec>("screenshots") {
    group = "verification"
    classpath = sourceSets["main"].runtimeClasspath
    mainClass.set("com.prostovpn.desktop.DevScreenshotKt")
    systemProperty("java.awt.headless", "true")
    systemProperty("skiko.renderApi", "SOFTWARE")
}

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

    commandLine(
        "go", "build",
        "-ldflags", "-s -w -H=windowsgui",
        "-trimpath",
        "-o", output.absolutePath,
        ".",
    )

    doFirst { output.parentFile.mkdirs() }
}

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

        ZipFile(wintunZip).use { archive ->
            val entry = archive.entries().asSequence()
                .firstOrNull { !it.isDirectory && it.name.replace('\\', '/').endsWith("bin/amd64/wintun.dll") }
                ?: error("В $wintunZip нет bin/amd64/wintun.dll")
            archive.getInputStream(entry).use { input ->
                target.outputStream().use { output -> input.copyTo(output) }
            }
        }

        val digest = MessageDigest.getInstance("SHA-256")
            .digest(target.readBytes())
            .joinToString("") { "%02x".format(it) }
        check(digest == expectedSha) {
            "Контрольная сумма wintun.dll не совпала:\n  ожидали $expectedSha\n  получили $digest"
        }
        logger.lifecycle("wintun.dll: контрольная сумма совпала")

        tmp.deleteRecursively()

        File(outDir, "amneziawg.exe").delete()
    }
}

/**
 * Скачивает бинарник из zip-архива релиза и сверяет контрольную сумму.
 *
 * Оба запасных движка — xray и tun2socks — лежат на GitHub одинаково
 * упакованными, поэтому качаем их одним кодом. Сумму проверяем обязательно:
 * это исполняемый файл, который окажется у людей на машинах.
 */
fun Task.fetchFromZip(
    url: String,
    entrySuffix: String,
    target: File,
    expectedSha: String,
) {
    val outDir = target.parentFile
    outDir.mkdirs()
    val tmp = File(outDir, "tmp").apply { mkdirs() }
    val archive = File(tmp, target.nameWithoutExtension + ".zip")

    logger.lifecycle("Скачиваю $url")
    URI(url).toURL().openStream().use { input ->
        archive.outputStream().use { output -> input.copyTo(output) }
    }

    ZipFile(archive).use { zip ->
        val entry = zip.entries().asSequence()
            .firstOrNull { !it.isDirectory && it.name.replace('\\', '/').endsWith(entrySuffix) }
            ?: error("В $archive нет $entrySuffix")
        zip.getInputStream(entry).use { input ->
            target.outputStream().use { output -> input.copyTo(output) }
        }
    }

    val digest = MessageDigest.getInstance("SHA-256")
        .digest(target.readBytes())
        .joinToString("") { "%02x".format(it) }
    check(digest == expectedSha) {
        "Контрольная сумма ${target.name} не совпала:\n  ожидали $expectedSha\n  получили $digest"
    }
    logger.lifecycle("${target.name}: контрольная сумма совпала")

    tmp.deleteRecursively()
}

tasks.register("fetchXray") {
    group = "distribution"
    description = "Скачивает xray.exe в resources/windows — движок запасного протокола"

    val target = tunnelResourcesDir.file("xray.exe").asFile
    outputs.file(target)

    doLast {
        fetchFromZip(
            url = "https://github.com/XTLS/Xray-core/releases/download/v26.3.27/Xray-windows-64.zip",
            entrySuffix = "xray.exe",
            target = target,
            expectedSha = "15c2d007954ac53ba69b80ec91242786b3c0b71d52649165b4ca1d5cc96ef8f1",
        )
    }
}

tasks.register("fetchTun2socks") {
    group = "distribution"
    description = "Скачивает tun2socks.exe — заворачивает трафик адаптера в прокси xray"

    val target = tunnelResourcesDir.file("tun2socks.exe").asFile
    outputs.file(target)

    doLast {
        fetchFromZip(
            url = "https://github.com/xjasonlyu/tun2socks/releases/download/v2.7.0/tun2socks-windows-amd64.zip",
            entrySuffix = "tun2socks-windows-amd64.exe",
            target = target,
            expectedSha = "076b3c3d6a372bae3f49f2b415a4105f70c30a3ed3caaed7979390e649892559",
        )
    }
}

listOf(
    "prepareAppResources",
    "packageMsi",
    "packageExe",
    "packageDistributionForCurrentOS",
    "createDistributable",
    "runDistributable",
).forEach { name ->
    tasks.matching { it.name == name }.configureEach {
        dependsOn("buildTunnel", "fetchWintun", "fetchXray", "fetchTun2socks")
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
