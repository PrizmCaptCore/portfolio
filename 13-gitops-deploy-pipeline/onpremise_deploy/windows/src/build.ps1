# Build a Windows exe via Windows container and copy it to .\out
# HOW TO USE: .\build.ps1 [-EnvFile env\.env]   (run in PowerShell, not WSL)
# Docker Desktop must be in Windows containers mode first.
param([string]$EnvFile = "env\.env")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$osType = docker info --format '{{.OSType}}'
if ($osType -ne 'windows') {
    Write-Error "Docker is not in Windows containers mode (current: $osType). Tray icon -> 'Switch to Windows containers...' and retry."
}

if (-not (Test-Path $EnvFile)) {
    Write-Error "NO ENV: $EnvFile - please run: Copy-Item env\.env.example env\.env"
}

# read KEY=VALUE pairs from the env file (strip surrounding quotes)
$vars = @{}
Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
        $vars[$Matches[1]] = $Matches[2].Trim().Trim('"')
    }
}

# only these two matter for the exe build (PKG_* is deb-only metadata)
$buildArgs = @()
foreach ($k in 'APP_ENTRY', 'BIN_NAME', 'NUITKA_EXTRA_ARGS') {
    if ($vars.ContainsKey($k)) { $buildArgs += '--build-arg', "$k=$($vars[$k])" }
}

docker build -f Dockerfile.windows -t nuitka-win @buildArgs .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# no BuildKit --output on the Windows engine, so extract via docker create + cp
New-Item -ItemType Directory -Force -Path out | Out-Null
$cid = docker create nuitka-win
try {
    docker cp "${cid}:C:\artifact\." out\
} finally {
    docker rm $cid | Out-Null
}
Get-ChildItem out\*.exe
