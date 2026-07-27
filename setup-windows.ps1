<#
.SYNOPSIS
  LocalBench Studio — Windows setup.
.DESCRIPTION
  Creates the Python virtual environment, installs backend dependencies, and
  installs/builds the frontend. Run once (or after pulling dependency changes).
#>
[CmdletBinding()]
param(
  [string]$Python = "python",
  [int]$Port = 8765,
  [string]$Host_ = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Venv = Join-Path $Backend ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# 1. Verify Python.
Write-Step "Checking Python..."
& $Python --version | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Error "Python not found. Install Python 3.11+ from https://www.python.org/ and ensure it is on PATH."
  exit 1
}
$pyver = (& $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
Write-Host "  Python $pyver detected."

# 2. Create venv.
if (-not (Test-Path $VenvPython)) {
  Write-Step "Creating virtual environment..."
  & $Python -m venv "$Venv"
}

# 3. Install backend deps.
Write-Step "Installing backend dependencies..."
& $VenvPython -m pip install --upgrade pip -q
& $VenvPython -m pip install -e "$Backend[dev]" -q
if ($LASTEXITCODE -ne 0) { Write-Error "Backend dependency installation failed."; exit 1 }

# 4. Install + build frontend.
Write-Step "Checking Node.js..."
try { node --version | Out-Null } catch { Write-Error "Node.js not found. Install Node 18+ from https://nodejs.org/"; exit 1 }

if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
  Write-Step "Installing frontend dependencies..."
  Push-Location $Frontend
  npm install
  Pop-Location
}

Write-Step "Building frontend (production)..."
Push-Location $Frontend
npm run build
$buildOk = $LASTEXITCODE
Pop-Location
if ($buildOk -ne 0) { Write-Error "Frontend build failed."; exit 1 }

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Run the application with: .\run-windows.ps1"
