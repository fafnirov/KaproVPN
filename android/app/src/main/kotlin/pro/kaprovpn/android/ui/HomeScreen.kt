package pro.kaprovpn.android.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import pro.kaprovpn.android.core.AppRepository
import pro.kaprovpn.android.core.DnsOption
import pro.kaprovpn.android.core.Storage
import pro.kaprovpn.android.core.XrayConfigBuilder
import pro.kaprovpn.android.vpn.XrayBridge

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    modifier: Modifier = Modifier,
    onConnect: (configJson: String, sessionName: String, dnsOption: DnsOption) -> Unit,
    onDisconnect: () -> Unit,
    onAddFirstConfig: () -> Unit = {},
) {
    val context = LocalContext.current
    val xrayState by XrayBridge.state.collectAsState()
    val configs by AppRepository.configs.collectAsState()
    val settings by AppRepository.settings.collectAsState()

    // Direct-sites грузим один раз — не меняется в рантайме (Phase 6
    // даст возможность редактировать, тогда переедет в Repository).
    val directSites = remember { Storage.loadDefaultSites(context) }

    val activeConfig = remember(configs, settings) {
        settings.activeConfigName?.let { name -> configs.find { it.name == name } }
    }
    val dnsOption = remember(settings) { DnsOption.get(settings.dnsOptionKey) }

    val isConnected = xrayState is XrayBridge.State.Connected
    val isBusy = xrayState is XrayBridge.State.Starting || xrayState is XrayBridge.State.Stopping
    var lastError by remember { mutableStateOf<String?>(null) }

    Scaffold(
        modifier = modifier,
        topBar = { TopAppBar(title = { Text("KaproVPN") }) },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(horizontal = 24.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(Modifier.weight(1f))

            // -- Активный конфиг или CTA --------------------------------
            if (activeConfig == null) {
                EmptyState(onAddClick = onAddFirstConfig)
            } else {
                ActiveConfigCard(
                    name = activeConfig.name,
                    protocol = activeConfig.protocol,
                    isConnected = isConnected,
                )
            }

            // -- Connection state ---------------------------------------
            Text(
                text = stateLabel(xrayState),
                style = MaterialTheme.typography.bodyMedium,
                color = when (xrayState) {
                    is XrayBridge.State.Failed -> Color(0xFFEF4444)
                    XrayBridge.State.Connected -> MaterialTheme.colorScheme.primary
                    else -> MaterialTheme.colorScheme.onSurfaceVariant
                },
            )

            lastError?.let { err ->
                Text("⚠ $err",
                    color = Color(0xFFEF4444),
                    style = MaterialTheme.typography.bodySmall)
            }

            Spacer(Modifier.size(8.dp))

            // -- Connect / Disconnect ----------------------------------
            if (!isConnected) {
                Button(
                    onClick = {
                        val cfg = activeConfig ?: return@Button
                        try {
                            val json = XrayConfigBuilder.buildConfigJson(
                                proxy = cfg,
                                directDomains = directSites,
                                dnsOption = dnsOption,
                            )
                            lastError = null
                            onConnect(json, cfg.name, dnsOption)
                        } catch (e: Throwable) {
                            lastError = "Ошибка генерации конфига: ${e.message}"
                        }
                    },
                    enabled = activeConfig != null && !isBusy,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.primary
                    ),
                ) {
                    Text(if (isBusy) "ПОДКЛЮЧЕНИЕ…" else "ВКЛЮЧИТЬ")
                }
            } else {
                Button(
                    onClick = onDisconnect,
                    enabled = !isBusy,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.error
                    ),
                ) { Text("ОТКЛЮЧИТЬ") }
            }

            // -- Bottom info --------------------------------------------
            Spacer(Modifier.weight(1f))
            Text(
                text = "${directSites.size} RU-сайтов идут напрямую · DNS: ${dnsOption.labelRu}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            )
        }
    }
}

@Composable
private fun ActiveConfigCard(
    name: String,
    protocol: String,
    isConnected: Boolean,
) {
    val accent = if (isConnected) MaterialTheme.colorScheme.primary
                 else MaterialTheme.colorScheme.surfaceVariant

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = accent),
        shape = RoundedCornerShape(16.dp),
    ) {
        Column(
            modifier = Modifier.padding(20.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text("Активный сервер",
                style = MaterialTheme.typography.bodySmall,
                color = if (isConnected)
                    MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.7f)
                else MaterialTheme.colorScheme.onSurfaceVariant)
            Text(
                text = name,
                style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold),
                color = if (isConnected) MaterialTheme.colorScheme.onPrimary
                else MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = protocol,
                style = MaterialTheme.typography.bodyMedium,
                color = if (isConnected)
                    MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.85f)
                else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun EmptyState(onAddClick: () -> Unit) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("KaproVPN",
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.SemiBold)
        Text(
            "Серверов пока нет.\nДобавь первый — открой вкладку «Серверы».",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center,
        )
        Spacer(Modifier.size(8.dp))
        OutlinedButton(onClick = onAddClick) {
            Text("Добавить сервер")
        }
    }
}

private fun stateLabel(s: XrayBridge.State): String = when (s) {
    XrayBridge.State.Idle -> "не подключено"
    XrayBridge.State.Starting -> "подключение…"
    XrayBridge.State.Connected -> "подключено"
    XrayBridge.State.Stopping -> "отключение…"
    is XrayBridge.State.Failed -> "ошибка: ${s.reason}"
}
