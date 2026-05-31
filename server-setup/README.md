# KaproTUN binaries mirror — server setup

This directory contains the bits you need to host xray-core /
tun2socks / wintun-driver on your own server so first-launch
downloads from KaproTUN clients go to you instead of GitHub.

**Why mirror at all?** GitHub releases CDN is occasionally flaky
from RU/CIS regions. A mirror under your own domain that you can
put behind a CDN (Cloudflare, Selectel CDN, etc.) is faster and
more available. The KaproTUN client always tries the mirror first,
falls back to upstream GitHub if the mirror is down — so even a
broken mirror doesn't break new installs.

## Target architecture

```
client.exe (first launch)
  ├─ wants xray.exe / tun2socks.exe / wintun.dll
  ├─ tries  https://kaprovpn.pro/files/<filename>     ← THIS server
  └─ falls back to original GitHub URLs on any failure
```

Files served by URL:

| URL | Source upstream |
|---|---|
| `/Xray-windows-64.zip`                | `github.com/XTLS/Xray-core` release asset |
| `/Xray-windows-arm64-v8a.zip`         | same |
| `/Xray-macos-64.zip`                  | same |
| `/Xray-macos-arm64-v8a.zip`           | same |
| `/Xray-linux-64.zip`                  | same |
| `/Xray-linux-arm64-v8a.zip`           | same |
| `/tun2socks-windows-amd64.zip`        | `github.com/xjasonlyu/tun2socks` release asset |
| `/tun2socks-darwin-amd64.zip`         | same |
| `/tun2socks-darwin-arm64.zip`         | same |
| `/tun2socks-linux-amd64.zip`          | same |
| `/tun2socks-linux-arm64.zip`          | same |
| `/wintun-0.14.1.zip`                  | `wintun.net` |
| `/hysteria-windows-amd64.exe` (+ darwin/linux, arm64) | `github.com/apernet/hysteria` release (tag `app/vX.Y.Z`) |
| `/KaproTUN-Setup-v<ver>.exe`          | KaproTUN GitHub release — **in-app auto-updater fallback** when github.com is unreachable from RU |

Total disk usage: ~150 MB at any given time.

## One-time setup on the VPS

Assumes Ubuntu 22.04 / Debian 12 with root SSH access. Adapt to
your distro as needed.

### 1. No DNS / no extra cert

The mirror is **path-based** — served from the existing `kaprovpn.pro`
site under `/files/`. No separate subdomain, no new DNS record, no new
TLS cert: it rides the `kaprovpn.pro` vhost certbot already manages.

### 2. nginx — add the `/files/` location

Paste the `location /files/` block from `nginx.conf.example` INTO the
existing `kaprovpn.pro` server block (the `:443` one), create the dir,
then reload:

```bash
mkdir -p /var/www/kaprovpn.pro/files
chown -R www-data:www-data /var/www/kaprovpn.pro/files
# edit the kaprovpn.pro vhost, paste the location block from
# nginx.conf.example (keep `alias` == /var/www/kaprovpn.pro/files/)
nginx -t && systemctl reload nginx
```

certbot rewrites the nginx site config to add the 443 server block
with the issued cert. Renewal is automatic via systemd timer.

### 3. Initial sync of upstream binaries

```bash
cp sync-binaries.sh /usr/local/bin/kaprotun-sync
chmod +x /usr/local/bin/kaprotun-sync
/usr/local/bin/kaprotun-sync   # first run — pulls everything
```

The script downloads from upstream into `/var/www/kaprovpn.pro/files/`
under the exact filenames the KaproTUN client expects. Total run
time on a 100 Mbit link: ~30 seconds.

### 4. Schedule weekly auto-resync

```bash
crontab -e
```
Add:
```
# Refresh KaproTUN client deps every Sunday 04:00 UTC
0 4 * * 0 /usr/local/bin/kaprotun-sync >> /var/log/kaprotun-sync.log 2>&1
```

That way new Xray-core releases land on the mirror within a week
of being published.

## Verifying the mirror works

From any machine:
```bash
curl -sI https://kaprovpn.pro/files/Xray-windows-64.zip | head -3
# Expect:
#   HTTP/2 200
#   server: nginx
#   content-type: application/zip
```

Then on a fresh Windows VM that's never run KaproTUN, install v1.2.3+
and watch the first-launch download progress dialog. It should
complete in 2-3 seconds (vs. 10-30 seconds against GitHub).
