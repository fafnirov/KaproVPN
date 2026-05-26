# run-emulator.ps1 -- launch the Android emulator in a network-isolated
# environment so it does NOT depend on the desktop KaproVPN being up.
#
# Why this exists
# ---------------
# When the desktop client is connected, its TUN interface (KaproTun) has
# InterfaceMetric=5 -- lower (= higher priority) than the WiFi adapter (45).
# QEMU/slirp picks the host's "first DNS" at emulator start, caches it for
# the whole session, and passes it down to Android as 10.0.2.3. That first
# DNS becomes 94.140.14.14 (AdGuard, configured on KaproTun).
#
# The moment the user disables the desktop VPN, KaproTun goes away. The
# emulator still has 10.0.2.3 -> 94.140.14.14 in its DHCP lease, the route
# to AdGuard is gone, and Chrome shows DNS_PROBE_FINISHED_NO_INTERNET --
# even though the Android-side VPN tunnel to 46.17.101.82 would still work
# (that IP already routes through WiFi, confirmed with Test-NetConnection).
#
# What this script does
# ---------------------
# 1. Kills any running emulator (existing instance still has the old DNS
#    cached; -dns-server only applies at launch).
# 2. Starts the emulator with -dns-server 1.1.1.1,8.8.8.8 -- slirp no longer
#    inherits host DNS.
# 3. With admin rights, pins routes for those DNS IPs through the WiFi
#    interface (RouteMetric=1) so the desktop VPN, if up, cannot grab them.
# 4. Removes those routes when the emulator exits.
#
# Usage
# -----
#   pwsh android\run-emulator.ps1                       # default AVD
#   pwsh android\run-emulator.ps1 -Avd Pixel_8_API_34
#   pwsh android\run-emulator.ps1 -NoRoutes             # skip admin-only step
#   pwsh android\run-emulator.ps1 -KeepRunning          # don't kill running AVD

[CmdletBinding()]
param(
    [string]$Avd = "Iphone_17_pro_max",
    [string[]]$Dns = @("1.1.1.1", "8.8.8.8"),
    [switch]$NoRoutes,
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"

# ---- 1. SDK paths -----------------------------------------------------------

$Sdk = $env:ANDROID_HOME
if (-not $Sdk) { $Sdk = $env:ANDROID_SDK_ROOT }
if (-not $Sdk) { $Sdk = "$env:LOCALAPPDATA\Android\Sdk" }
$EmulatorExe = Join-Path $Sdk "emulator\emulator.exe"
$AdbExe      = Join-Path $Sdk "platform-tools\adb.exe"

if (-not (Test-Path $EmulatorExe)) {
    throw "emulator.exe not found at $EmulatorExe. Install the Android SDK or set ANDROID_HOME."
}

# ---- 2. Stop existing emulator (if any) -------------------------------------

if (-not $KeepRunning) {
    $existing = & $AdbExe devices 2>$null |
        Where-Object { $_ -match '^emulator-\d+\s+device' } |
        ForEach-Object { ($_ -split '\s+')[0] }
    foreach ($e in $existing) {
        Write-Host "kill running emulator $e ..." -ForegroundColor DarkGray
        & $AdbExe -s $e emu kill 2>$null | Out-Null
    }
    if ($existing) { Start-Sleep -Seconds 2 }
}

# ---- 3. Pin DNS routes through WiFi (best-effort, needs admin) --------------
#
# We match the WiFi adapter by InterfaceDescription so localized adapter
# names ("Wireless Network Connection" / "Wi-Fi" / non-English equivalents)
# don't matter.

$wifiAdapter = Get-NetAdapter | Where-Object {
    $_.Status -eq 'Up' -and
    $_.InterfaceDescription -match 'Wi-?Fi|Wireless'
} | Select-Object -First 1

$wifiIfIndex = $null
$wifiGateway = $null
if ($wifiAdapter) {
    $wifiIfIndex = $wifiAdapter.ifIndex
    $wifiGateway = (Get-NetIPConfiguration -InterfaceIndex $wifiIfIndex -ErrorAction SilentlyContinue).IPv4DefaultGateway.NextHop
}

$addedRoutes = @()
if (-not $NoRoutes -and $wifiIfIndex -and $wifiGateway) {
    foreach ($ip in $Dns) {
        $prefix = "$ip/32"
        $hasRoute = Get-NetRoute -DestinationPrefix $prefix -InterfaceIndex $wifiIfIndex -ErrorAction SilentlyContinue
        if (-not $hasRoute) {
            try {
                New-NetRoute -DestinationPrefix $prefix -InterfaceIndex $wifiIfIndex `
                    -NextHop $wifiGateway -RouteMetric 1 -PolicyStore ActiveStore `
                    -ErrorAction Stop | Out-Null
                $addedRoutes += $prefix
                Write-Host "pinned $prefix -> WiFi" -ForegroundColor DarkGray
            } catch {
                Write-Warning "could not add route $prefix : $($_.Exception.Message)"
                Write-Warning "run PowerShell as Administrator for the full isolation (or pass -NoRoutes)."
            }
        }
    }
} elseif (-not $NoRoutes) {
    Write-Warning "WiFi adapter or gateway not found -- skipping DNS route pinning."
}

# ---- 4. Launch emulator -----------------------------------------------------

$dnsArg = ($Dns -join ',')
$emuArgs = @(
    "-avd", $Avd,
    "-dns-server", $dnsArg,
    "-no-snapshot-save",
    "-no-boot-anim"
)

Write-Host "starting AVD '$Avd' with DNS=$dnsArg ..." -ForegroundColor Cyan
$proc = Start-Process -FilePath $EmulatorExe -ArgumentList $emuArgs -PassThru

try {
    Write-Host "PID: $($proc.Id). Ctrl+C here -- stops emulator and unpins routes." -ForegroundColor DarkGray
    $proc.WaitForExit()
} finally {
    # ---- 5. Cleanup -----------------------------------------------------
    foreach ($prefix in $addedRoutes) {
        try {
            Get-NetRoute -DestinationPrefix $prefix -InterfaceIndex $wifiIfIndex `
                -ErrorAction SilentlyContinue |
                Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
            Write-Host "removed $prefix" -ForegroundColor DarkGray
        } catch {
            Write-Warning "could not remove route $prefix : $($_.Exception.Message)"
        }
    }
}
