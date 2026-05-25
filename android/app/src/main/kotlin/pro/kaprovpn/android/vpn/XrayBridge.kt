@file:Suppress("unused") // Phase 2: controller/callback/flows готовы к Phase 3, но пока не зовутся

package pro.kaprovpn.android.vpn

import android.content.Context
import android.util.Log
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import libv2ray.CoreCallbackHandler
import libv2ray.CoreController
import libv2ray.Libv2ray
import java.io.File

/**
 * Идиоматичная Kotlin-обёртка вокруг libv2ray ([Libv2ray] + [CoreController]).
 *
 * Архитектура:
 * - **Singleton.** Xray-core должен быть один на процесс (иначе порты,
 *   реквесты статистики и логи перепутаются). Соглашение: используем
 *   только этот object'.
 * - **Состояние.** Хранится в [state] (Flow). UI подписывается.
 * - **Логи xray.** Эмитятся в [logs] как [LogLine]. Подписаться может
 *   несколько потребителей (Logs-экран, краш-репортер, etc.).
 * - **`startLoop(...)` блокирующий.** Должен вызываться с IO-диспатчера —
 *   в этом API он обёрнут [start] с suspend-сигнатурой и переключением
 *   контекста.
 *
 * Соответствие десктоп-клиенту: примерно эквивалент `core/xray_process.py`
 * и `core/controller.py` (только Xray-часть, без TUN-routing — этим занимает-
 * ся [KaproVpnService] на этапе Phase 3).
 */
object XrayBridge {

    private const val TAG = "XrayBridge"

    private val _state = MutableStateFlow<State>(State.Idle)
    val state: StateFlow<State> = _state.asStateFlow()

    private val _logs = MutableSharedFlow<LogLine>(replay = 256, extraBufferCapacity = 256)
    val logs: SharedFlow<LogLine> = _logs.asSharedFlow()

    @Volatile private var controller: CoreController? = null
    @Volatile private var initialized: Boolean = false

    /**
     * Версия встроенного Xray-core. Доступно без вызова [init] — `checkVersionX`
     * не требует initCoreEnv. Используется для smoke-test'а интеграции AAR.
     */
    fun coreVersion(): String = try {
        Libv2ray.checkVersionX()
    } catch (e: Throwable) {
        Log.e(TAG, "checkVersionX failed", e)
        "unknown (${e.javaClass.simpleName})"
    }

    /**
     * Одноразовая инициализация рантайма. Зовётся из [App.onCreate] (или
     * lazy на первом start). Внутренне делает:
     *   1. Подготавливает private dir под runtime-state Xray (`<filesDir>/xray`).
     *   2. Зовёт [Libv2ray.initCoreEnv] с этим путём и ключом устройства.
     *
     * Безопасно вызывать многократно — повторные вызовы — no-op.
     */
    @Synchronized
    fun init(context: Context) {
        if (initialized) return
        try {
            val envDir = File(context.filesDir, "xray").apply { mkdirs() }
            // Второй параметр key — у Xray используется для шифрования
            // некоторых runtime-blob'ов (см. AndroidLibXrayLite README).
            // Для нашего use-case пустая строка ок.
            Libv2ray.initCoreEnv(envDir.absolutePath, "")
            initialized = true
            Log.i(TAG, "initCoreEnv → ${envDir.absolutePath}")
        } catch (e: Throwable) {
            Log.e(TAG, "initCoreEnv failed", e)
            // Не падаем — coreVersion() всё ещё работает без env, и UI
            // должен показать чёткую ошибку при попытке connect.
        }
    }

    /**
     * Состояния lifecycle Xray-core.
     *
     * Прогрессия в счастливом пути: `Idle → Starting → Connected → Stopping → Idle`.
     * Из любого состояния можно перейти в [Failed] (ошибка), оттуда — обратно в `Idle`.
     */
    sealed class State {
        object Idle : State()
        object Starting : State()
        object Connected : State()
        object Stopping : State()
        data class Failed(val reason: String) : State()
    }

    /**
     * Лог-строка от Xray-core. [severity] — числовой уровень из libv2ray
     * (0=Debug, 1=Info, 2=Warning, 3=Error — соответствие может отличаться,
     * проверять в UI рендере).
     */
    data class LogLine(val severity: Int, val message: String)

    /**
     * Внутренний CoreCallbackHandler. Получает callbacks от Go-стороны:
     * startup / shutdown signals + xray log lines.
     */
    private val callbackHandler = object : CoreCallbackHandler {
        override fun startup(): Long {
            Log.i(TAG, "CoreCallbackHandler.startup()")
            return 0L
        }

        override fun shutdown(): Long {
            Log.i(TAG, "CoreCallbackHandler.shutdown()")
            return 0L
        }

        override fun onEmitStatus(severity: Long, message: String): Long {
            // Forward в SharedFlow. tryEmit не блокирует — если буфер
            // забит (256 строк), новые дропаются. Для лог-потока это OK.
            _logs.tryEmit(LogLine(severity.toInt(), message))
            return 0L
        }
    }

    // TODO Phase 3: start(config: String, tunFd: Int) — suspend
    // TODO Phase 3: stop() — suspend
    // TODO Phase 3: queryStats / queryAllOutboundTrafficStats для UI bandwidth-виджета
    // TODO Phase 3: measureDelay(url) per-config для picker'а
}
