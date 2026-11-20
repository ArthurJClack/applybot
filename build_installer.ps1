# Builds dist\ApplyBot-Setup-<version>.exe (a proper Windows installer with shortcuts + uninstaller).
# Usage:  powershell -ExecutionPolicy Bypass -File build_installer.ps1  [-SkipExeBuild]
# Needs Inno Setup 6 - if it's missing, this script tells you the one-line winget install.
param([switch]$SkipExeBuild)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# 1. the exe itself
if (-not $SkipExeBuild -or -not (Test-Path "dist\ApplyBot.exe")) {
    & "$PSScriptRoot\build_exe.ps1"
    if ($LASTEXITCODE -ne 0) { throw "exe build failed" }
}

# 2. version from the source of truth
$m = Select-String -Path "applybot\__init__.py" -Pattern '__version__\s*=\s*"([^"]+)"'
if (-not $m) { throw "could not read __version__ from applybot\__init__.py" }
$version = $m.Matches[0].Groups[1].Value

# 3. find the Inno Setup compiler
$candidates = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$iscc = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) { $iscc = (Get-Command "ISCC.exe" -ErrorAction SilentlyContinue).Source }
if (-not $iscc) {
    Write-Host "Inno Setup is not installed. Install it once with:" -ForegroundColor Yellow
    Write-Host "    winget install -e --id JRSoftware.InnoSetup" -ForegroundColor Cyan
    Write-Host "then run this script again."
    exit 1
}

# 4. compile the installer
& $iscc "/DAppVersion=$version" "installer.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed" }

$setup = Get-Item "dist\ApplyBot-Setup-$version.exe"
Write-Host ""
Write-Host "Installer: $($setup.FullName)" -ForegroundColor Green
Write-Host ("  ApplyBot {0}  ({1:N1} MB) - per-user install, Start menu shortcut, uninstaller included" -f $version, ($setup.Length / 1MB))
