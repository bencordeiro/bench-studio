<#
.SYNOPSIS
  LocalBench Studio — Windows launcher.
.DESCRIPTION
  Verifies dependencies, builds the frontend if missing, applies database
  migrations, and starts the local application. Bound to 127.0.0.1 by default.
#>
[CmdletBinding()]
param(
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 8765,
  [switch]$SkipBuild,
  [switch]$LaunchBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Venv = Join-Path $Backend ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# Security warning if binding to a non-local interface.
if ($BindHost -ne "127.0.0.1" -and $BindHost -ne "localhost") {
  Write-Warning "Binding to $BindHost exposes the application on other network interfaces."
  Write-Warning "LocalBench Studio has NO multi-user authentication. Only do this on a trusted private network."
}

# 1. Verify dependencies.
if (-not (Test-Path $VenvPython)) {
  Write-Error "Virtual environment not found. Run .\setup-windows.ps1 first."
  exit 1
}
try { node --version | Out-Null } catch { Write-Warning "Node.js not on PATH; frontend build may be skipped." }

# 2. Build frontend if not already built or build requested.
$indexHtml = Join-Path $Frontend "dist\index.html"
if ((-not (Test-Path $indexHtml)) -and -not $SkipBuild) {
  Write-Step "Building frontend..."
  Push-Location $Frontend
  npm run build
  if ($LASTEXITCODE -ne 0) { Write-Error "Frontend build failed. Run .\setup-windows.ps1"; Pop-Location; exit 1 }
  Pop-Location
}

# 3. Start the application.
$env:LOCALBENCH_HOST = $BindHost
$env:LOCALBENCH_PORT = "$Port"
if ($LaunchBrowser) { $env:LOCALBENCH_LAUNCH_BROWSER = "1" }

$url = "http://${BindHost}:$Port"
Write-Step "Starting LocalBench Studio..."
Write-Host "  Open: $url" -ForegroundColor Green
Write-Host "  Press Ctrl+C to stop."
Write-Host ""

# Run from the backend directory so relative paths (alembic/) resolve.
Push-Location $Backend
try {
  & $VenvPython -m uvicorn app.main:app --host "$BindHost" --port $Port
} finally {
  Pop-Location
}
