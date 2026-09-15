plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "io.github.asadislam94.istadash"
    compileSdk = 35

    defaultConfig {
        applicationId = "io.github.asadislam94.istadash"
        minSdk = 28
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"

        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildTypes {
        getByName("release") {
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

dependencies {
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("com.google.android.material:material:1.11.0")
}

tasks.register<Sync>("syncPythonSources") {
    from("${rootProject.projectDir}/../istadash")
    into("src/main/python/istadash")
    exclude("**/__pycache__/**", "**/*.pyc")
}

tasks.named("preBuild") { dependsOn("syncPythonSources") }

tasks.matching { it.name.startsWith("merge") && it.name.endsWith("PythonSources") }.configureEach {
    dependsOn("syncPythonSources")
}

chaquopy {
    defaultConfig {
        version = "3.12"
        buildPython("python3.12")
        pip {
            install("beautifulsoup4>=4.12.3")
            install("Flask>=3.1.0")
            install("requests>=2.32.3")
        }
    }
}
