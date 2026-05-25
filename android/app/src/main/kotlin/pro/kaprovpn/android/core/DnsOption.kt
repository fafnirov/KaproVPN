package pro.kaprovpn.android.core

/**
 * Curated DNS choices, exposed в Settings.
 *
 * Прямой порт `kapro_vpn/core/dns_options.py`. Идея: 4 готовых варианта
 * (System / AdGuard / Cloudflare / Quad9), пользователь не пишет IP вручную.
 *
 * Семантика для xray:
 * - **DoH-серверы** ([dohServers]) идут в xray `dns` block — domain-based
 *   правила резолвятся шифрованно через них.
 * - **Plain IP** ([plainServers]) ставятся на TUN-интерфейс (VpnService
 *   Builder.addDnsServer) — резолвер OS видит эти, не ISP-овский.
 * - **Bypass IPs** ([bypassIps]) добавляются в routing с `outboundTag: direct`
 *   и в VpnService.Builder.addRoute(ip, 32) — чтобы DoH-over-443 от
 *   приложений, которые игнорируют OS DNS (Chrome, Yandex.Browser),
 *   не делал ненужный круг через VPN.
 *
 * Соответствие десктоп-клиенту 1:1 — конфиги между платформами совместимы.
 */
data class DnsOption(
    val key: String,            // stable id в settings
    val labelRu: String,
    val labelEn: String,
    val hintRu: String,
    val hintEn: String,
    val dohServers: List<String>,
    val plainServers: List<String>,
    val bypassIps: List<String>,
) {
    companion object {
        /** "Не трогать DNS" — что бы OS не отдал, то и используем. */
        val SYSTEM = DnsOption(
            key = "system",
            labelRu = "Системный",
            labelEn = "System",
            hintRu = "Использовать DNS как настроен в Android. Без изменений.",
            hintEn = "Use whatever DNS Android picked up. Don't change anything.",
            dohServers = emptyList(),
            plainServers = emptyList(),
            bypassIps = emptyList(),
        )

        /** AdGuard DNS + xray-rule блокирующий ~10k ad/tracker доменов. */
        val ADGUARD = DnsOption(
            key = "adguard",
            labelRu = "AdGuard — блокирует рекламу",
            labelEn = "AdGuard — blocks ads",
            hintRu = "Блокирует рекламу и трекеры — двойная защита: AdGuard DNS + ~10 000 ad-доменов через xray routing. Работает на любом сервере.",
            hintEn = "Blocks ads and trackers — two layers: AdGuard DNS + ~10K ad-domains via xray routing. Works on any server.",
            dohServers = listOf("https://dns.adguard-dns.com/dns-query"),
            plainServers = listOf("94.140.14.14", "94.140.15.15"),
            bypassIps = listOf("94.140.14.14", "94.140.15.15"),
        )

        /** Cloudflare 1.1.1.1 — быстрый и приватный, без фильтрации. */
        val CLOUDFLARE = DnsOption(
            key = "cloudflare",
            labelRu = "Cloudflare 1.1.1.1 — самый быстрый",
            labelEn = "Cloudflare 1.1.1.1 — fastest",
            hintRu = "Быстрый и приватный DNS. Без блокировок — нужен если ваш провайдер раздаёт медленный или мусорный DNS.",
            hintEn = "Fast and private. No filtering — use this if your ISP serves slow or junk DNS.",
            dohServers = listOf("https://1.1.1.1/dns-query", "https://1.0.0.1/dns-query"),
            plainServers = listOf("1.1.1.1", "1.0.0.1"),
            bypassIps = listOf("1.1.1.1", "1.0.0.1"),
        )

        /** Quad9 9.9.9.9 — security-focused, блокирует malware/phishing. */
        val QUAD9 = DnsOption(
            key = "quad9",
            labelRu = "Quad9 — блокирует malware-домены",
            labelEn = "Quad9 — blocks malware domains",
            hintRu = "Швейцарский, security-focused. Блокирует фишинг и malware, рекламу не трогает.",
            hintEn = "Swiss, security-focused. Blocks phishing and malware domains; doesn't touch ads.",
            dohServers = listOf("https://dns.quad9.net/dns-query"),
            plainServers = listOf("9.9.9.9", "149.112.112.112"),
            bypassIps = listOf("9.9.9.9", "149.112.112.112"),
        )

        /** Все опции в UI-порядке. System первым (sensible default). */
        val ALL: List<DnsOption> = listOf(SYSTEM, ADGUARD, CLOUDFLARE, QUAD9)

        private val BY_KEY: Map<String, DnsOption> = ALL.associateBy { it.key }

        const val DEFAULT_KEY = "system"

        /** Lookup по key. Незнакомые ключи → SYSTEM (defensive, для миграций). */
        fun get(key: String?): DnsOption = BY_KEY[key] ?: SYSTEM
    }
}
