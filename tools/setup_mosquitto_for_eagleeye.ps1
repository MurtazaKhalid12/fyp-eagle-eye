# =====================================================================
#  EagleEye — make the local Mosquitto broker reachable by the ESP32-CAM
#  RUN THIS AS ADMINISTRATOR (right-click > Run with PowerShell, or from an
#  elevated PowerShell prompt).
#
#  What it does (all required so the cam on your hotspot can reach the broker):
#    1. backs up mosquitto.conf
#    2. makes Mosquitto listen on ALL interfaces (so 192.168.137.1 works)
#    3. allows anonymous clients (the firmware connects with no user/pass)
#    4. opens TCP 1883 in Windows Firewall
#    5. restarts the broker and verifies
#
#  SECURITY NOTE: this opens the broker (no auth) to any device on your
#  hotspot/LAN. Fine for local testing. To undo, restore the .bak file,
#  remove the firewall rule "EagleEye Mosquitto 1883", and restart the service.
# =====================================================================

$ErrorActionPreference = "Stop"
$conf = "C:\Program Files\mosquitto\mosquitto.conf"

# must be admin
$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Host "ERROR: run this in an ADMINISTRATOR PowerShell." -ForegroundColor Red
  exit 1
}

Write-Host "1) backing up $conf ..."
Copy-Item $conf "$conf.eagleeye.bak" -Force
Write-Host "   backup -> $conf.eagleeye.bak"

Write-Host "2/3) patching listener + anonymous ..."
$raw = Get-Content $conf -Raw
if ($raw -notmatch "listener\s+1883\s+0\.0\.0\.0") {
  Add-Content $conf "`n# --- EagleEye: allow hotspot/LAN clients (ESP32) ---`nlistener 1883 0.0.0.0`nallow_anonymous true`n"
  Write-Host "   added: listener 1883 0.0.0.0 + allow_anonymous true"
} else {
  Write-Host "   already patched"
}

Write-Host "4) firewall rule for TCP 1883 ..."
if (-not (Get-NetFirewallRule -DisplayName "EagleEye Mosquitto 1883" -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -DisplayName "EagleEye Mosquitto 1883" -Direction Inbound -Protocol TCP -LocalPort 1883 -Action Allow -Profile Any | Out-Null
  Write-Host "   firewall rule added"
} else {
  Write-Host "   rule already exists"
}

Write-Host "5) restarting mosquitto ..."
Restart-Service mosquitto
Start-Sleep 2
Write-Host ("   service status: " + (Get-Service mosquitto).Status)

Write-Host "`n===== VERIFY: 1883 should now show 0.0.0.0:1883 (not just 127.0.0.1) ====="
netstat -ano | Select-String ":1883"
Write-Host "`nDone. If you see 0.0.0.0:1883 LISTENING, the ESP32 can now reach the broker." -ForegroundColor Green
