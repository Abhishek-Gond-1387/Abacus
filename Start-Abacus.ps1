$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Project virtual environment not found. Create it with: python -m venv .venv; then install dependencies with .\.venv\Scripts\python.exe -m pip install -e .'
}

if (-not [string]::IsNullOrWhiteSpace($env:ABACUS_CLIENT_API_KEYS)) {
    try {
        $configuredClients = $env:ABACUS_CLIENT_API_KEYS | ConvertFrom-Json
    } catch {
        throw 'ABACUS_CLIENT_API_KEYS is not valid JSON.'
    }
    if (-not ($configuredClients.PSObject.Properties.Name -contains 'default')) {
        throw 'Local auto-connect requires a default client in ABACUS_CLIENT_API_KEYS.'
    }
} elseif ([string]::IsNullOrWhiteSpace($env:ABACUS_API_KEY) -or $env:ABACUS_API_KEY.Length -lt 32) {
    $env:ABACUS_API_KEY = (& $python -c 'import secrets; print(secrets.token_urlsafe(48))').Trim()
    if ($LASTEXITCODE -ne 0 -or $env:ABACUS_API_KEY.Length -lt 32) {
        throw 'Could not create a local API key.'
    }
}

$env:ABACUS_LOCAL_UI_AUTO_AUTH = '1'
if ([string]::IsNullOrWhiteSpace($env:ABACUS_RUN_MODE)) {
    $env:ABACUS_RUN_MODE = 'inline'
}
$port = 8000
if (-not [string]::IsNullOrWhiteSpace($env:ABACUS_PORT)) {
    $parsedPort = 0
    if (-not [int]::TryParse($env:ABACUS_PORT, [ref]$parsedPort) -or $parsedPort -lt 1 -or $parsedPort -gt 65535) {
        throw 'ABACUS_PORT must be a valid TCP port.'
    }
    $port = $parsedPort
}

Push-Location $projectRoot
try {
    Write-Host "Abacus UI: http://127.0.0.1:$port/"
    Write-Host 'Local auto-connect is loopback-only. The API key is not printed or sent to the browser.'
    if ([string]::IsNullOrWhiteSpace($env:ABACUS_DATABASE_URL)) {
        Write-Host 'Database: persistent local SQLite under .abacus-data (or ABACUS_DATA_DIR if configured).'
    } else {
        Write-Host 'Database: using the configured ABACUS_DATABASE_URL.'
    }
    Write-Host 'Press Ctrl+C in this window to stop Abacus.'
    & $python -m uvicorn abacus.api:app --host 127.0.0.1 --port $port --workers 1
    if ($LASTEXITCODE -ne 0) {
        throw "Abacus stopped with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}
