package pro.kaprovpn.android.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.unit.dp
import pro.kaprovpn.android.core.AppRepository
import pro.kaprovpn.android.core.ParseError
import pro.kaprovpn.android.core.ProxyConfig
import pro.kaprovpn.android.core.ShareUrlParser

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConfigsScreen(modifier: Modifier = Modifier) {
    val configs by AppRepository.configs.collectAsState()
    val settings by AppRepository.settings.collectAsState()
    val activeName = settings.activeConfigName
    var showAddDialog by remember { mutableStateOf(false) }

    Scaffold(
        modifier = modifier,
        topBar = { TopAppBar(title = { Text("Серверы") }) },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = { showAddDialog = true },
                icon = { Icon(Icons.Filled.Add, contentDescription = "Добавить") },
                text = { Text("Добавить") },
            )
        },
    ) { innerPadding ->
        if (configs.isEmpty()) {
            EmptyConfigsState(modifier = Modifier.padding(innerPadding))
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(innerPadding),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(
                    horizontal = 16.dp, vertical = 12.dp
                ),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(configs, key = { it.name }) { cfg ->
                    ConfigRow(
                        config = cfg,
                        isActive = cfg.name == activeName,
                        onSelect = { AppRepository.setActiveConfig(cfg.name) },
                        onDelete = { AppRepository.removeConfig(cfg.name) },
                    )
                }
            }
        }
    }

    if (showAddDialog) {
        AddConfigDialog(
            onDismiss = { showAddDialog = false },
            onSave = { config ->
                AppRepository.addConfig(config)
                // Если это первый конфиг — сразу делаем его активным.
                if (configs.isEmpty()) AppRepository.setActiveConfig(config.name)
                showAddDialog = false
            },
        )
    }
}

@Composable
private fun ConfigRow(
    config: ProxyConfig,
    isActive: Boolean,
    onSelect: () -> Unit,
    onDelete: () -> Unit,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onSelect() },
        colors = CardDefaults.cardColors(
            containerColor = if (isActive)
                MaterialTheme.colorScheme.primaryContainer
            else MaterialTheme.colorScheme.surfaceVariant
        ),
        shape = RoundedCornerShape(12.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // Активный маркер (зелёная галка) или прозрачный placeholder.
            Box(
                modifier = Modifier
                    .size(24.dp)
                    .clip(CircleShape)
                    .background(
                        if (isActive) MaterialTheme.colorScheme.primary
                        else Color.Transparent
                    ),
                contentAlignment = Alignment.Center,
            ) {
                if (isActive) Icon(
                    Icons.Filled.Check,
                    contentDescription = "Активный",
                    tint = MaterialTheme.colorScheme.onPrimary,
                    modifier = Modifier.size(16.dp),
                )
            }
            Spacer(Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(config.name, style = MaterialTheme.typography.titleSmall)
                Text(
                    config.protocol,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = onDelete) {
                Icon(
                    Icons.Filled.Delete,
                    contentDescription = "Удалить",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun EmptyConfigsState(modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("Серверов пока нет", style = MaterialTheme.typography.headlineSmall)
        Spacer(Modifier.size(8.dp))
        Text(
            "Нажми «Добавить» внизу справа и вставь share-URL " +
                "от твоего VPN-провайдера (vless:// / vmess:// / trojan:// / ss://).",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AddConfigDialog(
    onDismiss: () -> Unit,
    onSave: (ProxyConfig) -> Unit,
) {
    var urlInput by remember { mutableStateOf("") }
    var customName by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Новый сервер") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedTextField(
                    value = urlInput,
                    onValueChange = { urlInput = it; error = null },
                    label = { Text("share-URL") },
                    placeholder = { Text("vless://...") },
                    minLines = 2,
                    maxLines = 5,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = customName,
                    onValueChange = { customName = it },
                    label = { Text("Имя (опционально)") },
                    placeholder = { Text("например, NL Server #2") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = {
            Button(onClick = {
                try {
                    var cfg = ShareUrlParser.parse(urlInput.trim())
                    if (customName.isNotBlank()) {
                        cfg = cfg.copy(name = customName.trim())
                    }
                    onSave(cfg)
                } catch (e: ParseError) {
                    error = "Не удалось распарсить: ${e.message}"
                } catch (e: Throwable) {
                    error = "Ошибка: ${e.message}"
                }
            }) { Text("Сохранить") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Отмена") }
        },
    )
}
