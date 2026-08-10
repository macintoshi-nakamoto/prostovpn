plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.prostovpn.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.prostovpn.app"
        minSdk = 26
        targetSdk = 35
        // Растёт с каждой выкладкой: с прежним versionCode установщик
        // Android может отказаться ставить сборку поверх старой
        versionCode = 6
        versionName = "1.0.4"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // Тестовая сборка: подписываем debug-ключом, чтобы APK ставился сразу
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
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
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")

    implementation(files("libs/awg-tunnel.aar"))
    implementation("androidx.annotation:annotation:1.9.1")
    implementation("androidx.collection:collection:1.5.0")

    testImplementation("junit:junit:4.13.2")
    // В unit-тестах android.jar заглушен, а SplitTunnel разбирает список
    // исключений через org.json — берём настоящую реализацию.
    testImplementation("org.json:json:20240303")
}
