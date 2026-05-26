package pro.kaprovpn.android.vpn

import android.content.Context
import android.util.Log
import hev.sockstun.TProxyService
import java.io.File

/**
 * Friendly Kotlin wrapper around [TProxyService]. Generates the
 * YAML config on the fly, hosts the blocking native call on a
 * dedicated thread, exposes idempotent start/stop.
 *
 * Why this exists: see [TProxyService] doc — libv2ray's
 * `startLoop(config, tunFd)` does NOT actually forward TUN packets.
 * This module is the missing link that turns "xray-core running" into
 * "system traffic actually proxied".
 *
 * Architecture in one line:
 *   kernel → TUN (VpnService) → THIS (tun2socks) → 127.0.0.1:2081
 *   (xray's socks-in inbound) → xray routing → proxy/direct outbound.
 */
object HevTunnel {

    private const val TAG = "HevTunnel"

    /** Must match `socks-in` listen_port in XrayConfigBuilder
     *  (`DEFAULT_LISTEN_PORT + 1` = 2081). */
    private const val SOCKS_PORT = 2081
    private const val SOCKS_ADDR = "127.0.0.1"

    /** Match VpnService.Builder.setMtu(1500) in [KaproVpnService].
     *  hev defaults to 8500 (jumbo frames) but our TUN is 1500 —
     *  mismatch made hev exit silently on first packet write. */
    private const val MTU = 1500
    private const val TASK_STACK_SIZE = 81920

    /** Must match `TUN_LOCAL_ADDR` in [KaproVpnService]. Without
     *  `tunnel.ipv4`, hev's YAML parse fails silently and the loop
     *  exits in ~1ms — the failure mode that bricked the first
     *  prototype. The .so reads it via `hev_config_get_tunnel_ipv4_address`. */
    private const val TUN_IPV4 = "10.255.0.2"

    @Volatile private var workerThread: Thread? = null

    /**
     * Starts the tun2socks loop. Idempotent — second call while already
     * running is a no-op.
     *
     * Note: `TProxyStartService` itself returns within ~30 ms — it does
     * NOT block. Internally it spawns lwip / event-loop threads inside the
     * .so and immediately returns. The wrapper thread we start below
     * exists purely so we can run `drainLogTo` *after* the native side
     * has had time to write something, and so we can keep a tidy
     * lifecycle handle. The real lifetime of the tunnel is controlled by
     * the native threads, not this Java [Thread].
     *
     * @param tunFd FD from `pfd.fd` (NOT `detachFd`) of the
     *   VpnService.Builder.establish() result. Lifetime is bound to the
     *   owning ParcelFileDescriptor — caller closes the pfd in
     *   disconnect(), which closes the fd.
     */
    @Synchronized
    fun start(context: Context, tunFd: Int) {
        val existing = workerThread
        if (existing != null && existing.isAlive) {
            Log.w(TAG, "start() called but worker already running — skip")
            return
        }
        val logFile = File(context.filesDir, LOG_NAME)
        // Wipe previous-run log so we always see only the current session's
        // output when debugging. The file is the only diagnostic surface for
        // hev's internal errors (stderr doesn't reach logcat by default).
        logFile.runCatching { delete() }
        val configFile = File(context.filesDir, CONFIG_NAME)
        configFile.writeText(buildYaml(logFile.absolutePath))
        val t = Thread {
            try {
                Log.i(TAG, "TProxyStartService(fd=$tunFd, cfg=${configFile.absolutePath})")
                TProxyService.TProxyStartService(configFile.absolutePath, tunFd)
                Log.i(TAG, "TProxyStartService returned — tunnel threads running in .so")
            } catch (e: Throwable) {
                Log.e(TAG, "TProxyStartService threw", e)
            } finally {
                // Drain whatever the native side wrote so far. We don't
                // know whether the .so is up-and-running or bailed early;
                // either way the log file is what tells us.
                drainLogTo(logFile)
            }
        }.apply {
            name = "hev-socks5-tunnel"
            isDaemon = true
        }
        workerThread = t
        t.start()
    }

    /** Tee hev's file log into logcat so we can see it via `adb logcat`. */
    private fun drainLogTo(logFile: File) {
        if (!logFile.exists()) {
            Log.i(TAG, "hev log file missing — native side likely crashed before init")
            return
        }
        try {
            logFile.bufferedReader().useLines { lines ->
                lines.forEach { Log.i(TAG, "hev: $it") }
            }
        } catch (e: Throwable) {
            Log.w(TAG, "drainLogTo failed", e)
        }
    }

    /**
     * Stops the tun2socks loop. The native call signals the loop;
     * the loop's [Thread] then exits naturally.
     */
    @Synchronized
    fun stop() {
        val t = workerThread ?: return
        if (!t.isAlive) {
            workerThread = null
            return
        }
        try {
            Log.i(TAG, "TProxyStopService — signalling worker to exit")
            TProxyService.TProxyStopService()
        } catch (e: Throwable) {
            Log.w(TAG, "TProxyStopService failed (ignored)", e)
        }
        // Wait briefly for graceful exit; if it doesn't happen, interrupt
        // and let GC clean up — the native side controls the fd anyway.
        try {
            t.join(2_000L)
        } catch (_: InterruptedException) {
        }
        workerThread = null
    }

    /** Stats counters from the native side. [uplinkBytes, downlinkBytes]. */
    fun stats(): LongArray = try {
        TProxyService.TProxyGetStats()
    } catch (_: Throwable) {
        longArrayOf(0L, 0L)
    }

    private fun buildYaml(logFilePath: String): String {
        // Build keeping the EXACT sockstun layout (LF endings, trailing \n,
        // no leading spaces) — hev's YAML parser is strict.
        //
        // Schema is whatever `hev_config_get_*` symbols inside
        // libhev-socks5-tunnel.so read. Reverse-engineered from the .so:
        //   - tunnel.ipv4 (REQUIRED) — local addr of the tun device
        //   - tunnel.mtu  (REQUIRED) — must match VpnService.setMtu
        //   - socks5.address / .port  — upstream SOCKS5 (xray socks-in)
        //   - socks5.udp 'udp'        — enable UDP relay over SOCKS5
        //   - misc.task-stack-size    — per-coroutine stack
        //   - misc.log-file <path>    — file path (stderr would go to /dev/null
        //                                on Android, so we use a real file and
        //                                tee its contents back into logcat)
        //   - misc.log-level 'debug'  — verbose visibility into hev internals
        return buildString {
            append("tunnel:\n")
            append("  ipv4: '").append(TUN_IPV4).append("'\n")
            append("  mtu: ").append(MTU).append('\n')
            append("  name: tun0\n")
            append("socks5:\n")
            append("  port: ").append(SOCKS_PORT).append('\n')
            append("  address: '").append(SOCKS_ADDR).append("'\n")
            append("  udp: 'udp'\n")
            append("misc:\n")
            append("  task-stack-size: ").append(TASK_STACK_SIZE).append('\n')
            append("  log-file: '").append(logFilePath).append("'\n")
            append("  log-level: debug\n")
        }
    }

    private const val CONFIG_NAME = "hev-tunnel.yaml"
    private const val LOG_NAME = "hev-tunnel.log"
}
