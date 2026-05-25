package pro.kaprovpn.android.core

import android.content.Context
import android.util.Log
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File

/**
 * Storage-слой для Android-клиента — порт `core/storage.py`.
 *
 * Что хранится и где:
 *   - **default_sites.json** — bundled в ассетах (sync'нутый из
 *     `kapro_vpn/data/default_sites.json` Gradle-task'ом). Read-only.
 *   - **configs.json** — список сохранённых ProxyConfig. Plain JSON в
 *     `<filesDir>/configs.json`. Содержит секреты (UUIDs, пароли).
 *   - **settings.json** — AppSettings (DNS option, active config, и т.п.).
 *
 * Encryption-at-rest TODO Phase 5.5: на десктопе DPAPI шифрует configs.json
 * на Windows. Android-аналог — Android Keystore + Cipher (AES/GCM/NoPadding)
 * или EncryptedSharedPreferences. Пока plain — filesDir уже per-app-private,
 * другие приложения её прочитать не могут без root. Решает 80% threat model.
 */
object Storage {

    private const val TAG = "Storage"
    private const val ASSET_DEFAULT_SITES = "default_sites.json"
    private const val FILE_CONFIGS = "configs.json"
    private const val FILE_SETTINGS = "settings.json"

    private val json = Json {
        ignoreUnknownKeys = true   // forward-compat: новые поля не ломают старые установки
        prettyPrint = false         // компактно
        encodeDefaults = true
    }

    // ====================================================================
    // --- Default sites (bundled assets, read-only) ----------------------
    // ====================================================================

    /**
     * Грузит дефолтный список direct-сайтов из ассетов. Bundled через
     * Gradle copy-task — один источник правды с десктоп-клиентом.
     *
     * Возвращает пустой список если файл не найден или сломан. В UI это
     * приводит к тому что split-routing просто не работает (всё через
     * туннель) — лучше чем краш приложения на старте.
     */
    fun loadDefaultSites(context: Context): List<String> {
        val raw = try {
            context.assets.open(ASSET_DEFAULT_SITES).bufferedReader().use { it.readText() }
        } catch (e: Throwable) {
            Log.e(TAG, "Не удалось открыть assets/$ASSET_DEFAULT_SITES", e)
            return emptyList()
        }
        return try {
            val root = Json.parseToJsonElement(raw).jsonObject
            val sites = root["sites"] as? JsonArray ?: return emptyList()
            sites
                .map { it.jsonPrimitive.content.trim().lowercase() }
                .filter { it.isNotEmpty() }
        } catch (e: Throwable) {
            Log.e(TAG, "Не удалось распарсить default_sites.json", e)
            emptyList()
        }
    }

    // ====================================================================
    // --- User configs (configs.json) ------------------------------------
    // ====================================================================

    private fun configsFile(context: Context): File =
        File(context.filesDir, FILE_CONFIGS)

    fun loadConfigs(context: Context): List<ProxyConfig> {
        val f = configsFile(context)
        if (!f.isFile) return emptyList()
        val raw = try {
            f.readBytes()
        } catch (e: Throwable) {
            Log.e(TAG, "configs read failed", e)
            return emptyList()
        }
        // Два формата: новый encrypted (с магией) и legacy plain JSON.
        // Распознаём по prefix'у — для миграции с pre-Phase-7 установок.
        val jsonBytes = if (SecretsStore.looksEncrypted(raw)) {
            try {
                SecretsStore.decrypt(raw)
            } catch (e: Throwable) {
                // Decrypt fail — обычно reinstall (ключ из старой установки
                // потерян). НЕ удаляем файл, чтобы пользователь мог сделать
                // adb pull для debug, но грузим пустой список.
                Log.e(TAG, "configs decrypt failed (reinstall?) — пустой список", e)
                return emptyList()
            }
        } else {
            // Legacy plain JSON — на лету парсим как обычно, при следующем
            // save оно перейдёт в encrypted формат.
            Log.i(TAG, "configs.json в legacy plain формате — будет зашифрован на следующем save")
            raw
        }
        return try {
            json.decodeFromString(
                ListSerializer(ProxyConfig.serializer()),
                jsonBytes.toString(Charsets.UTF_8),
            )
        } catch (e: Throwable) {
            Log.e(TAG, "configs JSON parse failed — пустой список", e)
            emptyList()
        }
    }

    fun saveConfigs(context: Context, configs: List<ProxyConfig>) {
        try {
            val text = json.encodeToString(ListSerializer(ProxyConfig.serializer()), configs)
            // Encrypt-at-rest: configs содержит UUID'ы / пароли / share-URL'ы —
            // полные креды. На pre-Phase-7 был plain JSON, теперь AES-256-GCM
            // через Android Keystore. Подробнее — [SecretsStore].
            val encrypted = SecretsStore.encrypt(text.toByteArray(Charsets.UTF_8))
            // Atomic-ish write: пишем в .tmp, потом rename. Если процесс упадёт
            // между write и rename, configs.json останется старым валидным.
            val f = configsFile(context)
            val tmp = File(f.parentFile, "${f.name}.tmp")
            tmp.writeBytes(encrypted)
            if (!tmp.renameTo(f)) {
                f.delete()
                tmp.renameTo(f)
            }
        } catch (e: Throwable) {
            Log.e(TAG, "saveConfigs failed", e)
        }
    }

    // ====================================================================
    // --- App settings (settings.json) -----------------------------------
    // ====================================================================

    private fun settingsFile(context: Context): File =
        File(context.filesDir, FILE_SETTINGS)

    fun loadSettings(context: Context): AppSettings {
        val f = settingsFile(context)
        if (!f.isFile) return AppSettings()
        return try {
            json.decodeFromString(AppSettings.serializer(), f.readText())
        } catch (e: Throwable) {
            Log.e(TAG, "settings.json повреждён — стартуем с default", e)
            AppSettings()
        }
    }

    fun saveSettings(context: Context, settings: AppSettings) {
        try {
            val text = json.encodeToString(AppSettings.serializer(), settings)
            val f = settingsFile(context)
            val tmp = File(f.parentFile, "${f.name}.tmp")
            tmp.writeText(text)
            if (!tmp.renameTo(f)) {
                f.delete()
                tmp.renameTo(f)
            }
        } catch (e: Throwable) {
            Log.e(TAG, "saveSettings failed", e)
        }
    }
}
