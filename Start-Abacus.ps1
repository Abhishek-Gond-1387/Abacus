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
        throw 'The local UI proxy needs a default client in ABACUS_CLIENT_API_KEYS.'
    }
    $defaultClient = $configuredClients.default
    if ($defaultClient -is [string]) {
        $proxyKey = $defaultClient
    } else {
        $proxyKey = $defaultClient.api_key
    }
    if ([string]::IsNullOrWhiteSpace($proxyKey) -or $proxyKey.Length -lt 32) {
        throw 'The default client key must contain at least 32 characters.'
    }
    if (-not [string]::IsNullOrWhiteSpace($env:ABACUS_API_KEY) -and $env:ABACUS_API_KEY -cne $proxyKey) {
        throw 'When using named clients, ABACUS_API_KEY must match the default client key for the local UI proxy.'
    }
    $env:ABACUS_API_KEY = $proxyKey
} elseif ([string]::IsNullOrWhiteSpace($env:ABACUS_API_KEY) -or $env:ABACUS_API_KEY.Length -lt 32) {
    $env:ABACUS_API_KEY = (& $python -c 'import secrets; print(secrets.token_urlsafe(48))').Trim()
    if ($LASTEXITCODE -ne 0 -or $env:ABACUS_API_KEY.Length -lt 32) {
        throw 'Could not create a local API key.'
    }
}

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

# Avoid silently opening a second launcher while the browser keeps talking to an
# older, AI-disabled process on the same port. Do not terminate unknown listeners.
$listeners = @()
try {
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
} catch {
    # Port preflight is best-effort on Windows editions without this cmdlet.
}
if ($listeners.Count -gt 0) {
    $listenerDetails = foreach ($listenerProcessId in ($listeners | Select-Object -ExpandProperty OwningProcess -Unique)) {
        $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $listenerProcessId" -ErrorAction SilentlyContinue
        if ($null -ne $processInfo) {
            '{0} (PID {1})' -f $processInfo.Name, $listenerProcessId
        } else {
            'PID {0}' -f $listenerProcessId
        }
    }
    $details = ($listenerDetails -join ', ')
    throw "Port $port is already in use by $details. Stop the old Abacus server with Ctrl+C in its original PowerShell window, then rerun this launcher."
}
$env:ABACUS_API_BASE_URL = "http://127.0.0.1:$port"
$env:ABACUS_UI_PROXY_ENABLED = '1'

Push-Location $projectRoot
try {
    Write-Host "Abacus UI: http://127.0.0.1:$port/"
    Write-Host 'Server-side API proxy is enabled for loopback requests only. The API key is not printed or sent to the browser.'
    $qaEnabled = $env:ABACUS_QA_ENABLED -match '^(1|true|yes)$'
    $geminiConfigured = -not [string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY)
    $geminiSelected = [string]::IsNullOrWhiteSpace($env:ABACUS_LLM_PROVIDER) -or $env:ABACUS_LLM_PROVIDER -eq 'gemini'
    if ($qaEnabled -and $geminiConfigured -and $geminiSelected) {
        Write-Host 'Ask AI: enabled with Gemini. The provider key stays in this server process and is not printed.'
    } else {
        Write-Host 'Ask AI: disabled. Run Start-Abacus-With-Gemini.ps1 and enter a non-empty Gemini key at its hidden prompt.'
    }
    Write-Host 'Custom code stays off until Docker sandbox verification passes and ABACUS_UNTRUSTED_EXECUTION=1.'
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
