param(
    [string]$OpenClawBin = "openclaw"
)

$ErrorActionPreference = "Stop"
$pluginRoot = Split-Path -Parent $PSScriptRoot
$isolatedHome = Join-Path $env:TEMP ("hotel-ota-openclaw-plugin-smoke-" + [guid]::NewGuid().ToString("N"))

try {
    $env:OPENCLAW_HOME = $isolatedHome
    & $OpenClawBin plugins install --link $pluginRoot
    & $OpenClawBin config validate
    & $OpenClawBin plugins inspect hotel-ota-feishu-auth --runtime --json
}
finally {
    Remove-Item -LiteralPath $isolatedHome -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item Env:OPENCLAW_HOME -ErrorAction SilentlyContinue
}
