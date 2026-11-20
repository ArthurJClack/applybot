# Sign the ApplyBot Live Firefox extension once so it installs permanently (no more "Load Temporary Add-on"
# after every Firefox restart). Free; needs a Mozilla Add-ons account.
#
# 1. Sign in at https://addons.mozilla.org, then open https://addons.mozilla.org/developers/addon/api/key/
#    and click "Generate new credentials".
# 2. Run this script from the ApplyBot folder:   powershell -ExecutionPolicy Bypass -File tools\sign_extension.ps1
#    It asks for the two credentials (they are not saved anywhere).
# 3. Drag the .xpi it creates (in applybot\live\signed) onto a Firefox window and click Add.
#
# "unlisted" means it is signed for your own use and never published on the Add-ons site.
$ErrorActionPreference = "Stop"
$issuer = Read-Host "JWT issuer (looks like user:12345:678)"
$secret = Read-Host "JWT secret"
$src = Join-Path $PSScriptRoot "..\applybot\live\extension"
$out = Join-Path $PSScriptRoot "..\applybot\live\signed"
New-Item -ItemType Directory -Force -Path $out | Out-Null
npx --yes web-ext@8 sign --channel=unlisted --source-dir $src --artifacts-dir $out --api-key $issuer --api-secret $secret
Write-Host "`nDone. Drag the .xpi from $out onto Firefox and click Add."
