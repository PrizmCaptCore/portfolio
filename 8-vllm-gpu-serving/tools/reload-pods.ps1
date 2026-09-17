<#
.SYNOPSIS
  Reload a RunPod Pod via POST /admin/reload.

.DESCRIPTION
  The Pod's entrypoint.sh pulls the latest server.py from GitHub on
  startup. Calling /admin/reload SIGTERMs the FastAPI process; the
  entrypoint loop then re-pulls and restarts. For inference/embedding/
  translate the vLLM subprocess survives, so reload is ~1-2s of API
  downtime. STT reloads its model in-process so expect ~30s.

  Authentication is the X-Internal-Key header, sourced from the
  RELAY_INTERNAL_KEY entry of .env (override with -InternalKey).

.PARAMETER Id
  Pod ID — the prefix before the dash in the RunPod proxy URL.
  E.g. for wss://<stt-pod-id>-8765.proxy.runpod.net/ the Id is
  "<stt-pod-id>". Find it in RunPod Console → Pod → Connect.

.PARAMETER Port
  Pod port. Default 8000 (inference / embedding / translate). Use
  8765 for STT.

.PARAMETER InternalKey
  Override the X-Internal-Key value. Defaults to RELAY_INTERNAL_KEY
  from .env.

.PARAMETER EnvFile
  Path to .env file (default: .env in current directory).

.EXAMPLE
  .\tools\reload-pods.ps1 -Id <inference-pod-id>
  Reload an inference / embedding / translate Pod (port 8000).

.EXAMPLE
  .\tools\reload-pods.ps1 -Id <stt-pod-id> -Port 8765
  Reload an STT Pod.

.EXAMPLE
  .\tools\reload-pods.ps1 -Id <inference-pod-id> -InternalKey "<internal-key>"
  Override the internal key (e.g. when .env points at a different env).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Id,
    [int]$Port = 8000,
    [string]$InternalKey = "",
    [string]$EnvFile = ".env"
)

# --- load .env for the internal key ------------------------------------------

if (-not $InternalKey) {
    if (Test-Path $EnvFile) {
        # Use the `foreach` keyword (not `ForEach-Object`) so the
        # $InternalKey assignment lands in this script's scope rather
        # than the pipeline cmdlet's child scope.
        foreach ($line in (Get-Content $EnvFile)) {
            $line = $line.Trim()
            if (-not $line -or $line.StartsWith("#")) { continue }
            if ($line -match "^RELAY_INTERNAL_KEY=(.*)$") {
                $InternalKey = $Matches[1].Trim()
                break
            }
        }
    }
    if (-not $InternalKey) {
        $InternalKey = $env:RELAY_INTERNAL_KEY
    }
}
if (-not $InternalKey) {
    Write-Error "RELAY_INTERNAL_KEY not found. Provide -InternalKey or add to $EnvFile."
    exit 1
}

# --- call /admin/reload -------------------------------------------------------

$url = "https://$Id-$Port.proxy.runpod.net/admin/reload"
Write-Host "POST $url"
try {
    $resp = Invoke-WebRequest -Method POST -Uri $url `
        -Headers @{ "X-Internal-Key" = $InternalKey } `
        -UseBasicParsing -ErrorAction Stop -TimeoutSec 10
    Write-Host "OK  $($resp.StatusCode)  $($resp.Content)" -ForegroundColor Green
} catch {
    $msg = $_.Exception.Message
    if ($_.Exception.Response) {
        $code = [int]$_.Exception.Response.StatusCode
        $msg = "HTTP $code"
    }
    Write-Host "FAIL  $msg" -ForegroundColor Red
    exit 1
}
