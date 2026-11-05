$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $projectRoot 'Start-Abacus.ps1'
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw 'Start-Abacus.ps1 was not found in the project folder.'
}

Write-Host 'For live AI answers, get a Gemini API key from https://aistudio.google.com/apikey.'
Write-Host 'Use a Free Tier project with billing off; this script never enables billing.'
Write-Host 'This launcher requires a key. Use Start-Abacus.ps1 only when you intentionally want AI disabled.'
$secureKey = Read-Host 'Gemini API key (hidden; required)' -AsSecureString
$environmentNames = @(
    'GEMINI_API_KEY', 'ABACUS_QA_ENABLED', 'ABACUS_LLM_PROVIDER', 'ABACUS_API_KEY',
    'ABACUS_API_BASE_URL', 'ABACUS_UI_PROXY_ENABLED', 'ABACUS_RUN_MODE', 'ABACUS_PORT'
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

if ($secureKey.Length -eq 0) {
    $secureKey.Dispose()
    throw 'No Gemini key was entered. Abacus was not started, so the browser cannot connect to an AI-disabled server by mistake.'
}

$keyPointer = [IntPtr]::Zero
$plainKey = $null
try {
    $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    $env:GEMINI_API_KEY = $plainKey
    $env:ABACUS_QA_ENABLED = '1'
    $env:ABACUS_LLM_PROVIDER = 'gemini'
    Write-Host 'Starting Abacus with live Gemini AI enabled. The key is kept in this server process and will not be printed or saved.'

    & $launcher
    if ($LASTEXITCODE -ne 0) {
        throw "Abacus stopped with exit code $LASTEXITCODE."
    }
} finally {
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
    $plainKey = $null
    if ($keyPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
    }
    $secureKey.Dispose()
}
