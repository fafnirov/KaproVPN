package hev.sockstun

/**
 * JNI bridge to heiher/sockstun's native `libhev-socks5-tunnel.so`.
 *
 * The class lives in package `hev.sockstun` intentionally — JNI symbol
 * names baked into the prebuilt .so are
 * `Java_hev_sockstun_TProxyService_*`. Moving the class anywhere else
 * would silently break the lookup (UnsatisfiedLinkError on first call).
 *
 * Library source: https://github.com/heiher/sockstun (GPL-3.0, same
 * licence as KaproVPN). Native blob comes from their `7.0` release
 * APK and lives in `app/src/main/jniLibs/<abi>/libhev-socks5-tunnel.so`.
 *
 * The C library does the actual TUN-to-SOCKS5 forwarding:
 *   - Reads packets from the TUN file descriptor we hand it.
 *   - For each TCP/UDP flow, opens a SOCKS5 client connection to the
 *     configured upstream (in our case xray-core's socks-in inbound
 *     at 127.0.0.1:2081).
 *   - Pipes bytes back into the TUN.
 *
 * Without this, xray-core would start fine but nothing would feed it
 * the system traffic — what we hit when the first version of the app
 * showed blank web pages despite "Connected" state.
 */
object TProxyService {

    init {
        System.loadLibrary("hev-socks5-tunnel")
    }

    /**
     * BLOCKING — runs the tun2socks event loop on the calling thread.
     * Returns only after [TProxyStopService] is invoked from elsewhere
     * (or on irrecoverable error inside the C code). Always call from
     * a dedicated worker thread.
     *
     * @param configPath absolute path to a YAML config file (see
     *   [pro.kaprovpn.android.vpn.HevTunnel] for the format we use).
     * @param fd TUN file descriptor obtained from
     *   `VpnService.Builder.establish()` (via `pfd.detachFd()`).
     *   Ownership transfers to the native code — do NOT close it
     *   from Kotlin afterwards.
     */
    @JvmStatic
    external fun TProxyStartService(configPath: String, fd: Int)

    /** Signals the running TProxyStartService loop to exit. */
    @JvmStatic
    external fun TProxyStopService()

    /** Returns [uplinkBytes, downlinkBytes]. */
    @JvmStatic
    external fun TProxyGetStats(): LongArray
}
