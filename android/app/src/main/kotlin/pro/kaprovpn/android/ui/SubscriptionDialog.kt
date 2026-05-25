package pro.kaprovpn.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import pro.kaprovpn.android.core.AppRepository
import pro.kaprovpn.android.core.Subscription

/**
 * Диалог импорта подписки. UX:
 *   1. URL input + кнопка «Загрузить»
 *   2. Прогресс (CircularProgressIndicator) пока fetch идёт
 *   3. Результат: «Найдено N серверов, M строк не распарсилось» +
 *      кнопка «Добавить все»
 *   4. После добавления — onAdded(count) → закрываем + snackbar в Configs
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SubscriptionDialog(
    onDismiss: () -> Unit,
    onAdded: (count: Int) -> Unit,
) {
    var url by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var result by remember { mutableStateOf<Subscription.Result?>(null) }
    val scope = rememberCoroutineScope()

    AlertDialog(
        onDismissRequest = { if (!loading) onDismiss() },
        title = { Text("Импорт по подписке") },
        text = {
            Column(
                modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(
                    "Если провайдер выдал ссылку на подписку (с base64-списком " +
                        "серверов внутри) — вставь её сюда, все сервера импор" +
                        "тируются за раз.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                OutlinedTextField(
                    value = url,
                    onValueChange = { url = it; error = null },
                    label = { Text("Subscription URL") },
                    placeholder = { Text("https://...") },
                    singleLine = false,
                    minLines = 2,
                    maxLines = 4,
                    enabled = !loading,
                    modifier = Modifier.fillMaxWidth(),
                )
                error?.let {
                    Text("⚠ $it", color = MaterialTheme.colorScheme.error)
                }
                result?.let { r ->
                    ResultSummary(r)
                }
                if (loading) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 8.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        CircularProgressIndicator()
                        Spacer(Modifier.size(8.dp))
                        Text("Загрузка…", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        },
        confirmButton = {
            val r = result
            if (r != null && r.configs.isNotEmpty()) {
                Button(onClick = {
                    AppRepository.addConfigs(r.configs)
                    onAdded(r.configs.size)
                }) { Text("Добавить все (${r.configs.size})") }
            } else {
                Button(
                    onClick = {
                        if (url.isBlank()) {
                            error = "Введите URL"
                            return@Button
                        }
                        error = null
                        result = null
                        loading = true
                        scope.launch {
                            try {
                                result = Subscription.import(url.trim())
                                if (result?.configs?.isEmpty() == true) {
                                    error = "Ничего не распарсилось. Проверь URL — " +
                                        "это точно subscription-ссылка?"
                                }
                            } catch (e: Throwable) {
                                error = "Ошибка загрузки: ${e.message}"
                            } finally {
                                loading = false
                            }
                        }
                    },
                    enabled = !loading && url.isNotBlank(),
                ) { Text(if (loading) "Загружаю…" else "Загрузить") }
            }
        },
        dismissButton = {
            TextButton(
                onClick = onDismiss,
                enabled = !loading,
            ) { Text(if (result != null) "Закрыть" else "Отмена") }
        },
    )
}

@Composable
private fun ResultSummary(r: Subscription.Result) {
    Column(
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Text(
            text = "Найдено ${r.configs.size} серверов" +
                if (r.errors.isNotEmpty()) " (${r.errors.size} ошибок)" else "",
            style = MaterialTheme.typography.bodyMedium,
            color = if (r.configs.isNotEmpty())
                MaterialTheme.colorScheme.primary
            else MaterialTheme.colorScheme.error,
        )
        if (r.configs.isNotEmpty()) {
            // Превью первых 5 имён — пользователь видит что импортирует.
            val preview = r.configs.take(5).joinToString("\n") { "• ${it.name}" }
            Text(
                text = if (r.configs.size > 5) "$preview\n…ещё ${r.configs.size - 5}" else preview,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
