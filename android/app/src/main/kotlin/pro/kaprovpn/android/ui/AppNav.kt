package pro.kaprovpn.android.ui

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import pro.kaprovpn.android.core.DnsOption

/**
 * Корневой контейнер приложения. Скаффолд с NavigationBar в bottomBar,
 * переключающий три экрана: Home / Configs / Settings.
 *
 * Без navigation-compose lib намеренно — у нас всего 3 tab'а, hot-swap
 * через sealed class + remember достаточно. Меньше зависимостей.
 */
@Composable
fun AppNav(
    onConnect: (configJson: String, sessionName: String, dnsOption: DnsOption) -> Unit,
    onDisconnect: () -> Unit,
    onNavigateToConfigs: () -> Unit = {},
) {
    var selectedTab by remember { mutableStateOf<Tab>(Tab.Home) }

    Scaffold(
        bottomBar = {
            NavigationBar {
                Tab.ALL.forEach { tab ->
                    NavigationBarItem(
                        selected = selectedTab == tab,
                        onClick = { selectedTab = tab },
                        icon = { Icon(tab.icon, contentDescription = tab.label) },
                        label = { Text(tab.label, style = MaterialTheme.typography.labelSmall) },
                    )
                }
            }
        }
    ) { padding ->
        // Phase 5: каждый экран сам делает свой padding относительно
        // bottom bar — пробрасываем innerPadding контрактом.
        val modifier = Modifier.padding(padding)
        when (selectedTab) {
            Tab.Home -> HomeScreen(
                modifier = modifier,
                onConnect = onConnect,
                onDisconnect = onDisconnect,
                onAddFirstConfig = { selectedTab = Tab.Configs },
            )
            Tab.Configs -> ConfigsScreen(modifier = modifier)
            Tab.Settings -> SettingsScreen(modifier = modifier)
        }
    }
}

/** Три вкладки — больше пока не планируется. */
sealed class Tab(val label: String, val icon: ImageVector) {
    object Home : Tab("Главная", Icons.Filled.Home)
    object Configs : Tab("Серверы", Icons.AutoMirrored.Filled.List)
    object Settings : Tab("Настройки", Icons.Filled.Settings)

    companion object {
        val ALL: List<Tab> = listOf(Home, Configs, Settings)
    }
}
