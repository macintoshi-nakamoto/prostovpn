import java.io.FileInputStream
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// Реквизиты релизного ключа держим вне репозитория: keystore.properties в .gitignore.
// Без файла собирается debug-подписью — чтобы репозиторий оставался собираемым у всех.
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
        // 24 — реальный пол, а не осторожность: libwg-quick.so требует strchrnul (API 24),
        // а awg-tunnel.aar объявляет minSdkVersion 24 и использует java.util.Optional (API 24).
        // Ниже 24 нативная часть не загрузится.
        minSdk = 24
        targetSdk = 35
        // Растёт с каждой выкладкой: с прежним versionCode установщик
        // Android может отказаться ставить сборку поверх старой.
        //
        // 1.1.0 была осознанным разрывом: приложение перешло с чужого
        // debug-ключа на постоянный релизный, поверх старых установок она
        // не вставала (Android не принимает смену подписи). С 1.1.1
        // обновления снова штатные.
        versionCode = 21
        versionName = "1.1.1"

        // Адрес панели: вход по логину и паролю и проверка обновлений идут
        // туда. Для своей сборки перебивается через -PpanelUrl=...
        // Адрес панели задаётся сборкой и в репозитории не хранится: он
        // принадлежит конкретной установке, а не коду.
        //
        //   ./gradlew assembleRelease -PpanelUrl=https://панель.ваш-домен
        //
        // Обязательно домен, а не голый IP: на IP публичный сертификат не
        // выпускается, а с самоподписанным вход молча не проходит.
        // Значение по умолчанию заведомо нерабочее — забытый параметр
        // сборки должно быть видно сразу.
        val panelUrl = (project.findProperty("panelUrl") as String?)
            ?: System.getenv("PANEL_URL")
            ?: "https://panel.example.com"
        buildConfigField("String", "PANEL_URL", "\"$panelUrl\"")
    }

    /*
    Отдельные APK по архитектурам плюс универсальный.

    Повод — телевизоры: типовой ТВ-бокс (Amlogic T5D и родня) 32-битный,
    arm64-каталог в abilist у него пуст, и универсальный APK он поставит,
    но будет носить в себе мёртвые 3,5 МБ arm64-библиотек при одном
    гигабайте памяти на всё. armeabi-v7a-сборка — то, что ставится на такие
    коробки; универсальная — ссылка «скачать» для телефонов, где думать об
    архитектуре не хочется.
    */
    splits {
        abi {
            isEnable = true
            reset()
            include("armeabi-v7a", "arm64-v8a")
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
            /*
            v1 нужен не ради старых Android (minSdk 24 покрывается v2), а ради
            сторонних установщиков: файловые менеджеры и магазины на EMUI/MIUI
            до сих пор проверяют META-INF и отказываются ставить APK без него.
            v3 даёт возможность ротации ключа в будущем без потери обновляемости.
            */
            enableV1Signing = true
            enableV2Signing = true
            enableV3Signing = true
        }
    }

    buildTypes {
        release {
            /*
            R8 без обфускации (см. proguard-rules.pro): из APK уходит
            неиспользуемая половина Compose и AndroidX — это меньше мегабайт
            на диске и заметно быстрее холодный старт на слабых телефонах
            из нижней половины парка. Имена классов не трогаем: JNI-мост
            wg-go находит Java по строковым именам.
            */
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            /*
            Отладочный ключ ломал установку там, где проверяют подпись: «Чистый режим»
            Huawei и AppGallery отклоняют APK с CN=Android Debug, Play Protect показывает
            предупреждение. Плюс debug-ключ свой на каждой машине, поэтому сборка с другого
            компьютера не вставала поверх предыдущей.
            */
            signingConfig = signingConfigs.getByName(if (hasReleaseKey) "release" else "debug")
        }
    }

    compileOptions {
        /*
        Обязательно при minSdk 24: org.amnezia.awg.config.InetEndpoint из awg-tunnel.aar
        использует java.time.Instant и java.time.Duration, а они появились только в API 26.
        Этот класс лежит на пути Config.parse у каждого подключения, и без десугаринга
        на Android 7.0/7.1 туннель не поднимался бы вовсе — причём молча: connect()
        оборачивает разбор в runCatching, который проглотил бы NoClassDefFoundError.
        */
        isCoreLibraryDesugaringEnabled = true
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        // BuildConfig.VERSION_NAME на экране поддержки: строка в локализации
        // отставала от versionName и врала уже на втором релизе
        buildConfig = true
    }

    packaging {
        jniLibs {
            // Несжатые .so с выравниванием 16 KB: обязательно для Android 15+
            // на устройствах с 16-килобайтными страницами, и экономит память везде.
            useLegacyPackaging = false
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
    // LifecycleResumeEffect: перечитать состояние фоновых ограничений, когда
    // пользователь вернулся из системных настроек
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.1")
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")

    implementation(files("libs/awg-tunnel.aar"))
    // Полный артефакт, а не _minimal: java.time есть только в полном
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.5")
    implementation("androidx.annotation:annotation:1.9.1")
    implementation("androidx.collection:collection:1.5.0")

    testImplementation("junit:junit:4.13.2")
    // В unit-тестах android.jar заглушен, а SplitTunnel разбирает список
    // исключений через org.json — берём настоящую реализацию.
    testImplementation("org.json:json:20240303")
}
