# Start Firefox with ApplyBot Live already loaded (no about:debugging clicking).
# Uses your normal Firefox profile, so your logins/sessions are all there.
#
# Run it (or double-click tools\Start Firefox with ApplyBot.bat):
#   powershell -ExecutionPolicy Bypass -File tools\start_firefox.ps1
#
# Needs Node.js (for npx web-ext). Firefox gets closed first because web-ext has to launch it itself.
# Leave the little console window open - closing it closes that Firefox.
$ErrorActionPreference = "Stop"
$src = (Resolve-Path (Join-Path $PSScriptRoot "..\applybot\live\extension")).Path

if (-not (Get-Command npx -ErrorAction SilentlyContinue)) {
    Write-Host "Node.js is missing. Install it from https://nodejs.org (LTS), then run this again."
    Read-Host "Press Enter to close"; exit 1
}

# Find the default profile from profiles.ini (the [Install...] section's Default= wins).
$root = Join-Path $env:APPDATA "Mozilla\Firefox"
$ini = Get-Content (Join-Path $root "profiles.ini")
$rel = $null; $section = ""
foreach ($line in $ini) {
    if ($line -match '^\[(.+)\]$') { $section = $Matches[1]; continue }
    if ($section -like "Install*" -and $line -match '^Default=(.+)$') { $rel = $Matches[1]; break }
}
if (-not $rel) {
    # Fallback: the profile marked Default=1
    $cur = @{}
    foreach ($line in $ini + "[end]") {
        if ($line -match '^\[') { if ($cur.Default -eq "1" -and $cur.Path) { $rel = $cur.Path; break }; $cur = @{}; continue }
        if ($line -match '^(\w+)=(.*)$') { $cur[$Matches[1]] = $Matches[2] }
    }
}
if (-not $rel) { Write-Host "Couldn't find your Firefox profile."; Read-Host "Press Enter to close"; exit 1 }
$prof = if ([IO.Path]::IsPathRooted($rel)) { $rel } else { Join-Path $root ($rel -replace '/', '\') }
Write-Host "Profile: $prof"

$ff = Get-Process firefox -ErrorAction SilentlyContinue
if ($ff) {
    Write-Host "Closing Firefox so it can restart with ApplyBot..."
    $ff | ForEach-Object { $_.CloseMainWindow() | Out-Null }
    Start-Sleep -Seconds 4
    Get-Process firefox -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 1
}

# --keep-profile-changes: everything you do stays in your real profile.
# --no-reload: ApplyBot reloads itself when needed.
npx --yes web-ext@8 run --source-dir $src --firefox-profile $prof --keep-profile-changes --no-reload `
    --start-url "http://127.0.0.1:8765/live/"
