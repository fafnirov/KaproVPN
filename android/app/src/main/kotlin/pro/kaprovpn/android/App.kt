package pro.kaprovpn.android

import android.app.Application
import pro.kaprovpn.android.vpn.XrayBridge

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        // Один раз готовим Xray-runtime (writable dir для geoip-кеша и т.п.).
        // Идемпотентно — повторные вызовы no-op.
        XrayBridge.init(this)
    }
}
