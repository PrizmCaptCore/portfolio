<#
.SYNOPSIS
    Launches the Gemma 4 E2B PoC WebSocket server using the gemma-poc conda env.

.DESCRIPTION
    Loads HF_TOKEN from the repo .env, points HF cache at the shared host
    directory (so a future containerized re-run shares the weights), and
    starts ws_server.py listening on 0.0.0.0:8765. RELAY_INTERNAL_KEY is
    intentionally NOT exported -- the PoC server runs unauthenticated for
    local-only testing.
#>
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$envFile  = Join-Path $repoRoot '.env'
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        $eq = $trimmed.IndexOf('=')
        if ($eq -lt 1) { continue }
        $key = $trimmed.Substring(0, $eq).Trim()
        $val = $trimmed.Substring($eq + 1).Trim().Trim('"').Trim("'")
        if (-not $val) { continue }
        # Skip RELAY_INTERNAL_KEY on purpose -- PoC must stay unauthenticated.
        if ($key -eq 'RELAY_INTERNAL_KEY') { continue }
        if (-not [Environment]::GetEnvironmentVariable($key)) {
            [Environment]::SetEnvironmentVariable($key, $val)
        }
    }
}

$env:HF_HOME  = Join-Path $repoRoot 'hf_cache'
if (-not $env:MODEL_ID) { $env:MODEL_ID = 'google/gemma-4-E2B-it' }

$python = 'C:\Users\<user>\miniconda3\envs\gemma-poc\python.exe'
$server = Join-Path $PSScriptRoot 'ws_server.py'

Write-Host "[launch] HF_HOME = $env:HF_HOME"
Write-Host "[launch] MODEL_ID = $env:MODEL_ID"
Write-Host "[launch] HF_TOKEN  = $(if ($env:HF_TOKEN) { "<set, $($env:HF_TOKEN.Length) chars>" } else { '<MISSING>' })"
Write-Host "[launch] starting $server"

& $python $server --host 0.0.0.0 --port 8765