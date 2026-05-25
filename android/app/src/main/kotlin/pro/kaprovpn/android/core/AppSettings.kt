package pro.kaprovpn.android.core

import kotlinx.serialization.Serializable

/**
 * Сохраняемые настройки приложения. Один JSON-файл в filesDir.
 *
 * Соответствие десктоп-клиенту: эквивалент `DEFAULT_SETTINGS` из
 * `core/storage.py`, минус Windows-специфичные ключи (autoconnect_on_launch
 * через registry, listen_port для HTTP-proxy-mode, и т.п.).
 */
@Serializable
data class AppSettings(
    /** Какой DnsOption активен (см. DnsOption.ALL). Default — system. */
    val dnsOptionKey: String = DnsOption.DEFAULT_KEY,

    /** Имя активного конфига (или null, если ни один не выбран). */
    val activeConfigName: String? = null,

    /** Автоподключаться при старте приложения. Default — off. */
    val autoconnectOnLaunch: Boolean = false,
)
