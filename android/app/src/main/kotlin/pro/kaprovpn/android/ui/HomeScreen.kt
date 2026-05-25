package pro.kaprovpn.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import pro.kaprovpn.android.vpn.XrayBridge

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen() {
    var coreVersion by remember { mutableStateOf<String?>(null) }

    Scaffold(
        topBar = { TopAppBar(title = { Text("KaproVPN") }) }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Spacer(Modifier.weight(1f))
            Text("KaproVPN", style = MaterialTheme.typography.headlineMedium)
            Text(
                "Phase 2: libv2ray AAR подключён. Дальше — VpnService + TUN.",
                style = MaterialTheme.typography.bodyMedium
            )

            Button(onClick = { /* TODO Phase 3: connect через VpnService */ }) {
                Text("ВКЛЮЧИТЬ")
            }

            Spacer(Modifier.weight(1f))

            // Smoke-test: дёргает Libv2ray.checkVersionX() через JNI.
            // Если кнопка показала версию — AAR подключён, .so для текущего
            // ABI загрузился, gomobile-биндинги работают. Это первый признак
            // того, что Phase 2 интеграция жива.
            OutlinedButton(onClick = { coreVersion = XrayBridge.coreVersion() }) {
                Text("Проверить Xray-core")
            }
            coreVersion?.let { v ->
                Text(
                    text = "version: $v",
                    style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace)
                )
            }

            Spacer(Modifier.weight(1f))
        }
    }
}
