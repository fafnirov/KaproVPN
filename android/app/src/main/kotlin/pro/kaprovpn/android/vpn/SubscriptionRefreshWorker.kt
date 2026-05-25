package pro.kaprovpn.android.vpn

import android.content.Context
import android.util.Log
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import pro.kaprovpn.android.core.AppRepository
import pro.kaprovpn.android.core.Subscription
import java.util.concurrent.TimeUnit

/**
 * Periodic background refresh of the user's subscription URL.
 *
 * Соответствие десктоп-клиенту: `gui/subscription_autorefresh.py` —
 * Sprint 2 на десктопе. Каждые ~12 часов фетчит ту же subscription
 * URL что юзер импортил из UI, парсит, мерджит результат в
 * [AppRepository]. Существующие имена обновляются (UUIDs провайдеры
 * рос rotate'ят), новые добавляются.
 *
 * Constraint'ы: только при наличии сети (любой — Wi-Fi или мобильная,
 * NetworkType.CONNECTED). Без charging-constraint — пользователю
 * нужны свежие конфиги когда они нужны, не когда телефон заряжается.
 *
 * WorkManager сам ребекаф'ит worker после перезагрузки устройства,
 * откладывает выполнение если нет сети, и в режиме Doze ждёт окна.
 */
class SubscriptionRefreshWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val settings = AppRepository.settings.value
        if (!settings.subscriptionAutorefresh) {
            Log.i(TAG, "auto-refresh выключен — skip")
            return Result.success()
        }
        val url = settings.subscriptionUrl
        if (url.isNullOrBlank()) {
            Log.i(TAG, "subscriptionUrl не задан — skip")
            return Result.success()
        }
        return try {
            Log.i(TAG, "refresh start: $url")
            val result = Subscription.import(url)
            if (result.configs.isNotEmpty()) {
                AppRepository.addConfigs(result.configs)
                Log.i(TAG, "refresh OK: ${result.configs.size} конфигов, " +
                    "${result.errors.size} ошибок")
            } else {
                Log.w(TAG, "refresh не нашёл конфигов в ответе — skip без удалений")
            }
            Result.success()
        } catch (e: Throwable) {
            Log.w(TAG, "refresh failed (будет повторён через интервал)", e)
            // Retry — WorkManager попробует снова в следующее окно.
            // Не делаем Result.failure(), потому что failure прекращает
            // periodic — а сеть может вернуться через час.
            Result.retry()
        }
    }

    companion object {
        private const val TAG = "SubRefreshWorker"
        const val WORK_NAME = "kaprovpn_subscription_refresh"

        /** Дефолтный интервал — соответствует десктопу (12 часов). */
        private const val INTERVAL_HOURS = 12L

        /**
         * Идемпотентно зарегистрировать periodic worker. Безопасно вызывать
         * на каждом App.onCreate — KEEP-policy сохранит существующий
         * schedule если он уже есть.
         */
        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<SubscriptionRefreshWorker>(
                INTERVAL_HOURS, TimeUnit.HOURS,
            ).setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            ).build()

            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                WORK_NAME,
                ExistingPeriodicWorkPolicy.KEEP,
                request,
            )
            Log.i(TAG, "scheduled (KEEP), interval=${INTERVAL_HOURS}h")
        }
    }
}
