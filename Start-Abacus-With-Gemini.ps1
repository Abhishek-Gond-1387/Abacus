$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $projectRoot 'Start-Abacus.ps1'
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw 'Start-Abacus.ps1 was not found in the project folder.'
}

Write-Host 'Get a Gemini API key from https://aistudio.google.com/apikey.'
Write-Host 'Use an account whose free tier is enough and whose billing is off; this script does not change billing settings.'
$secureKey = Read-Host 'Gemini API key (input is hidden and will not be saved)' -AsSecureString
if ($secureKey.Length -eq 0) {
    $secureKey.Dispose()
    throw 'A Gemini API key is required to enable live answers.'
}

$environmentNames = @(
    'GEMINI_API_KEY', 'ABACUS_QA_ENABLED', 'ABACUS_LLM_PROVIDER', 'ABACUS_API_KEY',
    'ABACUS_API_BASE_URL', 'ABACUS_UI_PROXY_ENABLED', 'ABACUS_RUN_MODE', 'ABACUS_PORT'
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$keyPointer = [IntPtr]::Zero
$plainKey = $null
try {
    $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    $env:GEMINI_API_KEY = $plainKey
    $env:ABACUS_QA_ENABLED = '1'
    $env:ABACUS_LLM_PROVIDER = 'gemini'

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
