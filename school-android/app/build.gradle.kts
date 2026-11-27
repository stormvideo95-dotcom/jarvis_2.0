plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.ictstorm.jarvisschool"
    compileSdk = 34
    defaultConfig {
        applicationId = "com.ictstorm.jarvisschool"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }
    buildTypes { getByName("debug") { isMinifyEnabled = false } }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    // Google's document scanner: finds the page edges, several pages, import from gallery, makes the PDF
    implementation("com.google.android.gms:play-services-mlkit-document-scanner:16.0.0-beta1")
}
