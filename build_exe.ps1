# Builds dist\ApplyBot.exe (a single-file Windows app).
# Usage:  powershell -ExecutionPolicy Bypass -File build_exe.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

& $py -m pip install --quiet --upgrade pyinstaller pillow
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

& $py tools\make_icon.py
if ($LASTEXITCODE -ne 0) { throw "icon generation failed" }

& $py tools\make_version_info.py
if ($LASTEXITCODE -ne 0) { throw "version info generation failed" }

& $py -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name ApplyBot `
    --icon assets\ApplyBot.ico `
    --version-file build\version_info.txt `
    --add-data "applybot\ui\static;applybot\ui\static" `
    --add-data "applybot\templates;applybot\templates" `
    --add-data "applybot\apply\scan_form.js;applybot\apply" `
    --collect-submodules applybot `
    --exclude-module jobspy `
    ApplyBot.pyw
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$exe = Resolve-Path dist\ApplyBot.exe
$ver = (Get-Item $exe).VersionInfo
Write-Host ""
Write-Host "Built: $exe" -ForegroundColor Green
Write-Host ("  {0}  v{1}  ({2:N1} MB)" -f $ver.FileDescription, $ver.ProductVersion, ((Get-Item $exe).Length / 1MB))
