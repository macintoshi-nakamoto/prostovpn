import java.io.File
import java.io.FileInputStream
import java.net.URI
import java.security.MessageDigest
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

val keystoreProperties = Properties().apply {
    val file = rootProject.file("keystore.properties")
    if (file.exists()) FileInputStream(file).use { load(it) }
}
val hasReleaseKey = keystoreProperties.getProperty("storeFile")
    ?.let { rootProject.file(it).exists() } == true

android {
    namespace = "com.prostovpn.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.prostovpn.app"

        minSdk = 24
        targetSdk = 35
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        versionCode = 28
        versionName = "1.1.8"

        val explicitPanelUrl = (project.findProperty("panelUrl") as String?)
            ?: System.getenv("PANEL_URL")
        val buildingRelease = gradle.startParameter.taskNames.any {
            it.contains("Release", ignoreCase = true)
        }
        if (buildingRelease && explicitPanelUrl.isNullOrBlank()) {
            throw GradleException(
                "Релизная сборка без адреса панели. Передайте -PpanelUrl=https://ваш-домен " +
                    "или задайте PANEL_URL в окружении: без него приложение обращается " +
                    "к panel.example.com и не работает ни у кого."
            )
        }
        val panelUrl = explicitPanelUrl ?: "https://panel.example.com"
        buildConfigField("String", "PANEL_URL", "\"$panelUrl\"")
    }

    splits {
        abi {
            isEnable = true
            reset()
            // Телефоны и приставки все на ARM, x86 в сборку не идёт. Но
            // проверять запасной протокол приходится на эмуляторе, а он
            // x86_64: -PemulatorAbi добавляет его, не трогая релиз.
            if (project.hasProperty("emulatorAbi")) {
                include("armeabi-v7a", "arm64-v8a", "x86_64")
            } else {
                include("armeabi-v7a", "arm64-v8a")
            }
            isUniversalApk = true
        }
    }

    signingConfigs {
        create("release") {
            if (hasReleaseKey) {
                storeFile = rootProject.file(keystoreProperties.getProperty("storeFile"))
                storePassword = keystoreProperties.getProperty("storePassword")
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
            }

            enableV1Signing = true
            enableV2Signing = true
            enableV3Signing = true
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )

            signingConfig = signingConfigs.getByName(if (hasReleaseKey) "release" else "debug")
        }
    }

    compileOptions {
        isCoreLibraryDesugaringEnabled = true
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true

        buildConfig = true
    }

    packaging {
        jniLibs {
            useLegacyPackaging = false
        }
        resources {
            // Базы гео из libv2ray занимают 28 МБ и нужны только маршрутизации
            // по странам, которой у нас нет: весь трафик идёт в один узел.
            excludes += setOf("assets/geoip.dat", "assets/geosite.dat", "assets/geoip-only-cn-private.dat")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.06.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.1")

    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.1")
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")

    implementation(files("libs/awg-tunnel.aar"))
    // Ядро запасного протокола. Файл качает задача fetchXrayAar — в репозитории
    // его нет: 59 МБ в истории git не нужны никому.
    implementation(files("libs/libv2ray.aar"))

    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.5")
    implementation("androidx.annotation:annotation:1.9.1")
    implementation("androidx.collection:collection:1.5.0")

    testImplementation("junit:junit:4.13.2")
    // Проверка запасного протокола идёт только на устройстве: поднять
    // VpnService из обычного теста нельзя, права даёт лишь сам процесс
    // приложения.
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    // Согласие на VPN даёт системный диалог, и в проверке его надо нажать.
    androidTestImplementation("androidx.test.uiautomator:uiautomator:2.3.0")

    testImplementation("org.json:json:20240303")
}

/**
 * Скачивает и сверяет то, чего нет в репозитории.
 *
 * Ядро xray весит 59 МБ, и держать его в git значит раздуть историю навсегда.
 * Качаем при сборке и обязательно сверяем сумму: это код, который окажется у
 * людей на телефонах.
 */
fun download(url: String, target: File, expectedSha: String) {
    if (target.isFile) {
        val have = MessageDigest.getInstance("SHA-256")
            .digest(target.readBytes())
            .joinToString("") { "%02x".format(it) }
        if (have == expectedSha) return
    }
    target.parentFile.mkdirs()
    logger.lifecycle("Скачиваю $url")
    URI(url).toURL().openStream().use { input ->
        target.outputStream().use { output -> input.copyTo(output) }
    }
    val digest = MessageDigest.getInstance("SHA-256")
        .digest(target.readBytes())
        .joinToString("") { "%02x".format(it) }
    check(digest == expectedSha) {
        "Контрольная сумма ${target.name} не совпала: ожидали $expectedSha, получили $digest"
    }
    logger.lifecycle("${target.name}: контрольная сумма совпала")
}

tasks.register("fetchXrayAar") {
    group = "build setup"
    description = "Скачивает libv2ray.aar — ядро запасного протокола"
    val target = File(projectDir, "libs/libv2ray.aar")
    outputs.file(target)
    doLast {
        download(
            "https://github.com/2dust/AndroidLibXrayLite/releases/download/v26.8.20/libv2ray.aar",
            target,
            "670cf11d9d10a6bb6548ac4f593acfa4339155732f6f8de4d45923f30a74deed",
        )
    }
}

tasks.matching { it.name.startsWith("pre") && it.name.endsWith("Build") }.configureEach {
    dependsOn("fetchXrayAar")
}
