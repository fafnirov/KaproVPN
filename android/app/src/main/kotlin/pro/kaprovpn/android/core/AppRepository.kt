package pro.kaprovpn.android.core

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Single source of truth для конфигов + настроек приложения.
 *
 * Singleton — инициализируется один раз в [App.onCreate] вызовом [init].
 * После этого все экраны Compose подписываются на [configs] / [settings]
 * через `collectAsState()`, а мутации идут через методы CRUD.
 *
 * Соответствие десктоп-клиенту: эквивалент `core/storage.py` + слой
 * controller-state из `core/controller.py` (settings dict). Здесь
 * совмещены, потому что Compose UI хочет один observable holder.
 */
object AppRepository {

    private lateinit var ctx: Context

    private val _configs = MutableStateFlow<List<ProxyConfig>>(emptyList())
    val configs: StateFlow<List<ProxyConfig>> = _configs.asStateFlow()

    private val _settings = MutableStateFlow(AppSettings())
    val settings: StateFlow<AppSettings> = _settings.asStateFlow()

    @Synchronized
    fun init(context: Context) {
        ctx = context.applicationContext
        _configs.value = Storage.loadConfigs(ctx)
        _settings.value = Storage.loadSettings(ctx)
    }

    // -- configs ---------------------------------------------------------

    /**
     * Добавить или обновить конфиг. Уникальность по [ProxyConfig.name] —
     * существующий с тем же именем переписывается. Это удобно для
     * повторного импорта одной и той же подписки.
     */
    fun addConfig(config: ProxyConfig) {
        val without = _configs.value.filterNot { it.name == config.name }
        val updated = without + config
        _configs.value = updated
        Storage.saveConfigs(ctx, updated)
        // Если ничего не было активного — делаем новый активным,
        // чтобы Home сразу мог подключиться. Для пакетного импорта
        // это сработает только на ПЕРВЫЙ конфиг из пачки.
        if (_settings.value.activeConfigName == null) {
            setActiveConfig(config.name)
        }
    }

    /**
     * Пакетная замена-merge — для импорта подписки. Существующие
     * конфиги с теми же именами перезаписываются (UUID/host могли
     * обновиться у провайдера). Имена которых нет — остаются.
     */
    fun addConfigs(newConfigs: List<ProxyConfig>) {
        if (newConfigs.isEmpty()) return
        val newNames = newConfigs.map { it.name }.toSet()
        val merged = _configs.value.filterNot { it.name in newNames } + newConfigs
        _configs.value = merged
        Storage.saveConfigs(ctx, merged)
        if (_settings.value.activeConfigName == null) {
            setActiveConfig(newConfigs.first().name)
        }
    }

    fun removeConfig(name: String) {
        val updated = _configs.value.filterNot { it.name == name }
        _configs.value = updated
        Storage.saveConfigs(ctx, updated)
        // Если удалили active — сбрасываем активный, чтобы Home показал "выбери".
        if (_settings.value.activeConfigName == name) {
            updateSettings { it.copy(activeConfigName = null) }
        }
    }

    fun setActiveConfig(name: String?) {
        // Сначала валидируем — нельзя выставить активным имя которого нет в списке
        // (защита от стейлёного state'а).
        if (name != null && _configs.value.none { it.name == name }) return
        updateSettings { it.copy(activeConfigName = name) }
    }

    fun activeConfig(): ProxyConfig? = _settings.value.activeConfigName?.let { name ->
        _configs.value.find { it.name == name }
    }

    // -- settings --------------------------------------------------------

    fun setDnsOption(key: String) {
        // Защита: незнакомый key заменяем на SYSTEM (как и DnsOption.get).
        val resolved = DnsOption.get(key).key
        updateSettings { it.copy(dnsOptionKey = resolved) }
    }

    fun dnsOption(): DnsOption = DnsOption.get(_settings.value.dnsOptionKey)

    fun setAutoconnect(enabled: Boolean) {
        updateSettings { it.copy(autoconnectOnLaunch = enabled) }
    }

    /**
     * Применить мутацию к настройкам + сохранить + опубликовать в Flow.
     * Single-shot — каждая мутация перезаписывает settings.json целиком,
     * что нормально для такого мелкого объекта.
     */
    private fun updateSettings(transform: (AppSettings) -> AppSettings) {
        val next = transform(_settings.value)
        _settings.value = next
        Storage.saveSettings(ctx, next)
    }
}
