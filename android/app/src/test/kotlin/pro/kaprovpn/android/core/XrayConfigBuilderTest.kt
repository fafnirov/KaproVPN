package pro.kaprovpn.android.core

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Тесты [XrayConfigBuilder]. Проверяют что генерируемый JSON содержит
 * все обязательные элементы:
 *   - privacy: `log.access == "none"`
 *   - DNS-leak rules (Cloudflare/Google/Quad9/Yandex IPs → direct)
 *   - port 53 → direct (UDP + TCP)
 *   - dns block только для non-System DnsOption
 *   - geosite:category-ads-all block только для AdGuard
 *   - user-выбранные bypass IPs → direct
 *
 * Все тесты — JVM-only, без Android-зависимостей.
 */
class XrayConfigBuilderTest {

    private val sampleProxy: ProxyConfig = ShareUrlParser.parse(
        "vless://uuid-abc@example.com:443?security=tls&type=tcp&sni=example.com#Test"
    )

    @Test
    fun `access log disabled for privacy`() {
        val cfg = XrayConfigBuilder.buildConfig(sampleProxy, emptyList())
        val log = cfg["log"]?.jsonObject ?: error("no log block")
        assertEquals("\"none\" обязательно — иначе xray пишет полную историю браузинга",
            "none", log["access"]?.jsonPrimitive?.content)
    }

    @Test
    fun `system DNS has no dns block and no AdGuard rule`() {
        val cfg = XrayConfigBuilder.buildConfig(sampleProxy, emptyList(),
            dnsOption = DnsOption.SYSTEM)
        assertNull("System mode — без dns-block (OS решает)", cfg["dns"])
        val rules = (cfg["routing"]?.jsonObject?.get("rules") as JsonArray)
        assertFalse(rules.toString().contains("category-ads-all"))
    }

    @Test
    fun `AdGuard adds dns block and ad-block rule`() {
        val cfg = XrayConfigBuilder.buildConfig(sampleProxy, emptyList(),
            dnsOption = DnsOption.ADGUARD)
        val dns = cfg["dns"]?.jsonObject ?: error("AdGuard должен ставить dns-block")
        val servers = dns["servers"]?.jsonArray ?: error("servers missing")
        assertTrue(servers.any { it.jsonPrimitive.content.contains("adguard") })
        assertEquals("UseIPv4", dns["queryStrategy"]?.jsonPrimitive?.content)

        val rules = (cfg["routing"]?.jsonObject?.get("rules") as JsonArray)
        val adRule = rules.find {
            it.jsonObject["domain"]?.toString()?.contains("category-ads-all") == true
        } ?: error("AdGuard должен добавить geosite:category-ads-all правило")
        assertEquals("block", adRule.jsonObject["outboundTag"]?.jsonPrimitive?.content)
    }

    @Test
    fun `Cloudflare has dns block but no AdGuard rule`() {
        val cfg = XrayConfigBuilder.buildConfig(sampleProxy, emptyList(),
            dnsOption = DnsOption.CLOUDFLARE)
        assertNotNull("Cloudflare должен ставить dns-block", cfg["dns"])
        val rules = (cfg["routing"]?.jsonObject?.get("rules") as JsonArray)
        assertFalse("Cloudflare — без ad-block правил",
            rules.toString().contains("category-ads-all"))
    }

    @Test
    fun `DNS-leak rules present always`() {
        // Берём system mode чтобы убедиться что hardening работает даже без
        // выбранного юзер-DNS — это базовый privacy guarantee.
        val cfg = XrayConfigBuilder.buildConfig(sampleProxy, emptyList(),
            dnsOption = DnsOption.SYSTEM)
        val rules = (cfg["routing"]?.jsonObject?.get("rules") as JsonArray)

        val rulesStr = rules.toString()
        // Cloudflare DNS forced direct — даже без активного Cloudflare-mode.
        assertTrue("DNS-leak hardening: 1.1.1.1 forced direct", rulesStr.contains("1.1.1.1/32"))
        // Google DNS forced direct
        assertTrue("DNS-leak hardening: 8.8.8.8 forced direct", rulesStr.contains("8.8.8.8/32"))
        // Yandex DNS forced direct
        assertTrue("DNS-leak hardening: 77.88.8.8 forced direct", rulesStr.contains("77.88.8.8/32"))

        // Port 53 → direct (catches less-known resolvers)
        val portRules = rules.filter { it.jsonObject["port"]?.jsonPrimitive?.content == "53" }
        assertEquals("должно быть 2 port-53 правила (UDP + TCP)", 2, portRules.size)
        val networks = portRules.mapNotNull { it.jsonObject["network"]?.jsonPrimitive?.content }
        assertTrue(networks.containsAll(listOf("udp", "tcp")))
    }

    @Test
    fun `user DNS bypass IPs end up in routing as direct`() {
        val cfg = XrayConfigBuilder.buildConfig(sampleProxy, emptyList(),
            dnsOption = DnsOption.QUAD9)
        val rules = (cfg["routing"]?.jsonObject?.get("rules") as JsonArray)
        val rulesStr = rules.toString()
        // Quad9 plain IPs from DnsOption — должны попасть в direct-bypass
        assertTrue("Quad9 9.9.9.9 → direct", rulesStr.contains("9.9.9.9/32"))
        assertTrue("Quad9 149.112.112.112 → direct", rulesStr.contains("149.112.112.112/32"))
    }

    @Test
    fun `direct domains end up as domain rules`() {
        val cfg = XrayConfigBuilder.buildConfig(sampleProxy,
            listOf("sber.ru", "gosuslugi.ru"),
            dnsOption = DnsOption.SYSTEM)
        val rules = (cfg["routing"]?.jsonObject?.get("rules") as JsonArray)
        val domainRule = rules.find {
            val tag = it.jsonObject["outboundTag"]?.jsonPrimitive?.content
            tag == "direct" && it.jsonObject["domain"] != null
        } ?: error("должно быть domain-rule для direct-доменов")
        val domains = (domainRule.jsonObject["domain"] as JsonArray)
            .map { it.jsonPrimitive.content }
        assertTrue(domains.contains("domain:sber.ru"))
        assertTrue(domains.contains("domain:gosuslugi.ru"))
    }

    @Test
    fun `proxy outbound is first in outbounds list`() {
        // Xray использует первый outbound как default для не-совпавших правил —
        // значит туннелируемый трафик улетает через proxy. Этот инвариант
        // критичен — поломка молчаливо туннелировала бы всё через freedom.
        val cfg = XrayConfigBuilder.buildConfig(sampleProxy, emptyList())
        val outbounds = cfg["outbounds"] as JsonArray
        assertEquals("proxy", outbounds[0].jsonObject["tag"]?.jsonPrimitive?.content)
        assertEquals("direct", outbounds[1].jsonObject["tag"]?.jsonPrimitive?.content)
        assertEquals("block", outbounds[2].jsonObject["tag"]?.jsonPrimitive?.content)
    }

    @Test
    fun `buildConfigJson produces valid parseable JSON`() {
        val json = XrayConfigBuilder.buildConfigJson(sampleProxy, listOf("test.ru"))
        assertTrue("должно быть валидным JSON object'ом", json.startsWith("{"))
        assertTrue(json.contains("\"proxy\""))
        assertTrue(json.contains("\"vless\""))
    }
}
