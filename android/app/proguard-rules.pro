# =====================================================================
#  KaproVPN Android — ProGuard / R8 rules
# =====================================================================

-keepattributes *Annotation*, InnerClasses, Signature, Exceptions
-renamesourcefileattribute SourceFile
-keepattributes SourceFile, LineNumberTable

# ---------------------------------------------------------------------
# kotlinx.serialization — see https://github.com/Kotlin/kotlinx.serialization
# ---------------------------------------------------------------------
-keepclassmembers class kotlinx.serialization.json.** {
    *** Companion;
}
-keepclasseswithmembers class kotlinx.serialization.json.** {
    kotlinx.serialization.KSerializer serializer(...);
}

# Our @Serializable data classes (ProxyConfig, AppSettings, ...) — keep
# their generated $$serializer and Companion so kotlinx-serialization can
# find them via reflection at runtime.
-keep,includedescriptorclasses class pro.kaprovpn.android.core.**$$serializer { *; }
-keepclassmembers class pro.kaprovpn.android.core.** {
    *** Companion;
}
-keepclasseswithmembers class pro.kaprovpn.android.core.** {
    kotlinx.serialization.KSerializer serializer(...);
}

# ---------------------------------------------------------------------
# libv2ray (Go-mobile generated JNI bindings)
# ---------------------------------------------------------------------
# Native callbacks: libv2ray's Go code calls back into JVM through
# CoreCallbackHandler. R8 must not rename / strip that interface or
# methods, иначе callbacks упадут с NoSuchMethodError.
-keep class libv2ray.** { *; }
-keep interface libv2ray.** { *; }
-keep class go.** { *; }
-keep interface go.** { *; }

# Our implementation of CoreCallbackHandler — keep callbacks intact.
-keep class pro.kaprovpn.android.vpn.XrayBridge** {
    long startup();
    long shutdown();
    long onEmitStatus(long, java.lang.String);
}

# ---------------------------------------------------------------------
# WorkManager
# ---------------------------------------------------------------------
# WorkManager creates Worker classes via reflection (by class name in
# work info). R8 would otherwise rename them.
-keep class * extends androidx.work.CoroutineWorker {
    public <init>(android.content.Context, androidx.work.WorkerParameters);
}
-keep class * extends androidx.work.Worker {
    public <init>(android.content.Context, androidx.work.WorkerParameters);
}

# ---------------------------------------------------------------------
# Compose — AGP handles defaults, but be explicit about no-stripping
# the generated R class fields used by stringResource().
# ---------------------------------------------------------------------
-keepclassmembers class **.R$* {
    public static <fields>;
}

# ---------------------------------------------------------------------
# Stack trace readability — keep line numbers for crash reports.
# ---------------------------------------------------------------------
-keepattributes SourceFile,LineNumberTable
