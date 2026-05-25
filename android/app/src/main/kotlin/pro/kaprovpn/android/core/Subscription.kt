package pro.kaprovpn.android.core

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URI
import java.util.Base64

/**
 * Импорт подписок — порт `kapro_vpn/core/subscription.py`.
 *
 * Большинство VPN-провайдеров (dns.army, BMV, AmneziaFree, ...) выдают
 * один URL, который возвращает base64-encoded список share-URL'ов — по
 * одному на строку. Этот модуль скачивает тело, декодирует, парсит
 * каждый share-URL через [ShareUrlParser] и возвращает готовый
 * [SubscriptionResult].
 *
 * Format detection (как в десктопе):
 * - Если тело содержит явные share-URL (vless://, vmess://, ...) →
 *   парсим как plain.
 * - Иначе пробуем base64-decode; если декод даёт scheme'ы — используем.
 *
 * DPI-fallback (десктоп): можно фетчить через локальный xray-tunnel
 * если direct-request заблокирован DPI. На Android пока не нужно —
 * пользователь может сначала включить VPN и потом импортнуть.
 */
object Subscription {

    private val SUPPORTED_SCHEMES = listOf(
        "vless://", "vmess://", "trojan://", "ss://",
        "hysteria2://", "hy2://",
    )

    private const val USER_AGENT =
        "KaproVPN-Android/0.1.0-dev (Android; +https://github.com/fafnirov/KaproVPN)"

    private const val CONNECT_TIMEOUT_MS = 10_000
    private const val READ_TIMEOUT_MS = 20_000

    /**
     * Результат загрузки и парсинга подписки.
     *
     * @param configs успешно распарсенные ProxyConfig
     * @param errors короткие human-readable строки об ошибках (по одной
     *   на каждый share-URL, который не распарсился)
     * @param rawLines сколько кандидатов мы попытались распарсить —
     *   полезно для UI «5 из 7 распарсилось»
     */
    data class Result(
        val configs: List<ProxyConfig>,
        val errors: List<String>,
        val rawLines: Int,
    )

    /**
     * Вытаскивает share-URL'ы из тела ответа подписки.
     *
     * Сначала проверяет нет ли в теле уже plain share-URL'ов. Если нет —
     * пробует base64-decode (с автоматическим fix padding'а). Возвращает
     * пустой список если ничего извлечь не удалось.
     */
    fun parseBody(body: String): List<String> {
        val trimmed = body.trim()
        if (trimmed.isEmpty()) return emptyList()

        // Сначала пробуем plain. Если в теле нет ни одного известного
        // scheme — попробуем base64.
        val candidates = mutableListOf(trimmed)
        if (SUPPORTED_SCHEMES.none { sch -> sch in trimmed }) {
            try {
                // Fix padding до длины кратной 4 (как в parser._b64DecodePadded)
                val padded = trimmed + "=".repeat((-trimmed.length).mod(4))
                val normalized = padded.replace('-', '+').replace('_', '/')
                val decoded = Base64.getDecoder().decode(normalized)
                    .toString(Charsets.UTF_8)
                if (SUPPORTED_SCHEMES.any { sch -> sch in decoded }) {
                    // base64 победил → используем его как primary candidate
                    candidates.add(0, decoded)
                }
            } catch (_: Exception) {
                // Не base64 — оставляем только plain
            }
        }

        for (text in candidates) {
            val urls = text.lines()
                .map { it.trim() }
                .filter { line ->
                    line.isNotEmpty() &&
                        !line.startsWith("#") &&
                        SUPPORTED_SCHEMES.any { sch -> line.startsWith(sch) }
                }
            if (urls.isNotEmpty()) return urls
        }
        return emptyList()
    }

    /**
     * Парсит body и собирает результат. Делится с `import` чтобы можно
     * было использовать на manually-pasted body (когда сервер блокирует
     * запросы из приложений — пользователь копирует тело из браузера).
     */
    fun resultFromBody(body: String): Result {
        val shareUrls = parseBody(body)
        val configs = mutableListOf<ProxyConfig>()
        val errors = mutableListOf<String>()
        for (url in shareUrls) {
            try {
                configs.add(ShareUrlParser.parse(url))
            } catch (e: ParseError) {
                val short = url.take(60) + (if (url.length > 60) "…" else "")
                errors.add("$short — ${e.message}")
            }
        }
        return Result(configs = configs, errors = errors, rawLines = shareUrls.size)
    }

    /**
     * Скачать subscription URL + распарсить. Suspend — внутри переключается
     * на [Dispatchers.IO] потому что [HttpURLConnection] блокирующий.
     *
     * Бросает [java.io.IOException] на сетевые проблемы (timeout, DNS,
     * 4xx/5xx). UI ловит и показывает.
     */
    suspend fun import(url: String): Result = withContext(Dispatchers.IO) {
        val conn = (URI(url).toURL().openConnection() as HttpURLConnection).apply {
            connectTimeout = CONNECT_TIMEOUT_MS
            readTimeout = READ_TIMEOUT_MS
            requestMethod = "GET"
            instanceFollowRedirects = true
            setRequestProperty("User-Agent", USER_AGENT)
            // Provider'ы иногда возвращают gzip — JVM сама расжмёт если
            // accept-encoding не задан, но явно ставим identity для
            // предсказуемости (избегаем двойного decode).
            setRequestProperty("Accept-Encoding", "identity")
        }
        try {
            val code = conn.responseCode
            if (code !in 200..299) {
                throw java.io.IOException(
                    "HTTP $code от $url: ${conn.responseMessage}"
                )
            }
            val body = conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
            resultFromBody(body)
        } finally {
            conn.disconnect()
        }
    }
}
