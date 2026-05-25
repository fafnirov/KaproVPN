package pro.kaprovpn.android.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

/**
 * Тесты [Subscription] — только parseBody / resultFromBody, без сети.
 * Сетевой [Subscription.import] требует HTTP-mock либо живой сервер —
 * это уже integration test, не unit (Phase 6 не реализовано).
 */
class SubscriptionTest {

    private val sample1 = "vless://uuid1@host1.com:443?security=tls#Server 1"
    private val sample2 = "trojan://pw@host2.com:443?security=tls#Server 2"
    private val sample3 = "ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ=@h:8388#Server 3"

    @Test
    fun `plain text body extracts share-URLs`() {
        val body = "$sample1\n$sample2\n$sample3"
        val urls = Subscription.parseBody(body)
        assertEquals(3, urls.size)
        assertEquals(sample1, urls[0])
        assertEquals(sample3, urls[2])
    }

    @Test
    fun `plain text ignores comments and blanks`() {
        val body = """
            # KaproVPN test subscription
            # generated at 2026-05-25

            $sample1

            # second server
            $sample2
        """.trimIndent()
        val urls = Subscription.parseBody(body)
        assertEquals(2, urls.size)
    }

    @Test
    fun `base64 encoded body is detected and decoded`() {
        val plain = "$sample1\n$sample2"
        val b64 = Base64.getEncoder().encodeToString(plain.toByteArray())
        val urls = Subscription.parseBody(b64)
        assertEquals(2, urls.size)
        assertEquals(sample1, urls[0])
    }

    @Test
    fun `URL-safe base64 without padding is detected`() {
        val plain = "$sample1\n$sample2\n$sample3"
        // URL-safe alphabet (- and _ instead of + and /), без padding
        val b64 = Base64.getUrlEncoder().withoutPadding()
            .encodeToString(plain.toByteArray())
        val urls = Subscription.parseBody(b64)
        assertEquals(3, urls.size)
    }

    @Test
    fun `body with no valid URLs returns empty`() {
        assertEquals(emptyList<String>(), Subscription.parseBody(""))
        assertEquals(emptyList<String>(), Subscription.parseBody("hello world"))
        assertEquals(emptyList<String>(), Subscription.parseBody("# only comments"))
    }

    @Test
    fun `resultFromBody parses good and tracks bad URLs`() {
        val body = """
            $sample1
            not-a-valid-scheme://garbage
            $sample2
        """.trimIndent()
        val result = Subscription.resultFromBody(body)
        // not-a-valid-scheme:// не начинается ни с одной supported scheme,
        // значит parseBody его пропустит на этапе фильтрации — не считаем
        // как ошибку парсинга. Только распознанные URL'ы участвуют.
        assertEquals(2, result.rawLines)
        assertEquals(2, result.configs.size)
        assertEquals(0, result.errors.size)
        assertEquals("Server 1", result.configs[0].name)
    }

    @Test
    fun `resultFromBody surfaces ParseError as error`() {
        // Невалидный vless (нет порта) — известный scheme, но parser
        // не сможет его распарсить → errors[]
        val brokenVless = "vless://uuid@host?security=tls"
        val body = "$sample1\n$brokenVless"
        val result = Subscription.resultFromBody(body)
        assertEquals(2, result.rawLines)
        assertEquals(1, result.configs.size)
        assertEquals(1, result.errors.size)
        assertTrue("error должна содержать обрезанный URL",
            result.errors[0].contains("vless://uuid@host"))
    }
}
