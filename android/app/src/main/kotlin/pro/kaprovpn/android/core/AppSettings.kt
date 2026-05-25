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

    /** URL последней импортированной subscription. Используется
     *  background-worker'ом раз в 12 часов чтобы перетянуть свежий
     *  список конфигов (провайдеры часто рос rotate'ят UUIDs/endpoints). */
    val subscriptionUrl: String? = null,

    /** Включён ли auto-refresh подписки. Default — on, чтобы новые
     *  пользователи сразу получали свежие конфиги без ручного re-import. */
    val subscriptionAutorefresh: Boolean = true,
)
