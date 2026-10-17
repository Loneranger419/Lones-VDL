# Quick local run: verify deps, start API here, open Vite in a second terminal.
# Usage:
#   powershell -File scripts\dev.ps1
#   powershell -File scripts\dev.ps1 -Install   # create venv / pip / npm if missing
#   powershell -File scripts\dev.ps1 -ApiOnly
#   powershell -File scripts\dev.ps1 -WebOnly

[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$ApiOnly,
    [switch]$WebOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-WarnStep([string]$Message) {
    Write-Host "!!  $Message" -ForegroundColor Yellow
}

function Assert-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found on PATH: $Name"
    }
}

function Get-VenvPython {
    $candidate = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $candidate) {
        return $candidate
    }
    return $null
}

function Ensure-Venv {
    $py = Get-VenvPython
    if ($null -ne $py) {
        return $py
    }
    if (-not $Install) {
        throw "Missing .venv. Create it once with: powershell -File scripts\dev.ps1 -Install"
    }
    Write-Step "Creating .venv"
    Assert-Command "python"
    python -m venv (Join-Path $Root ".venv")
    $py = Get-VenvPython
    if ($null -eq $py) {
        throw "Failed to create .venv\Scripts\python.exe"
    }
    return $py
}

function Ensure-PythonPackage([string]$PythonExe) {
    Write-Step "Checking Python package (lones_vdl)"
    & $PythonExe -c "import lones_vdl, fastapi, uvicorn" 2>$null
    if ($LASTEXITCODE -eq 0) {
        return
    }
    if (-not $Install) {
        throw "Python deps missing in .venv. Fix with: powershell -File scripts\dev.ps1 -Install"
    }
    Write-Step "Installing Python package editable with [dev]"
    & $PythonExe -m pip install -U pip
    & $PythonExe -m pip install -e ".[dev]"
    if ($LASTEXITCODE -ne 0) {
        throw 'pip install -e ".[dev]" failed'
    }
    & $PythonExe -c "import lones_vdl, fastapi, uvicorn"
    if ($LASTEXITCODE -ne 0) {
        throw "Import check failed after install"
    }
}

function Ensure-EnvFile {
    $envFile = Join-Path $Root ".env"
    $example = Join-Path $Root ".env.example"
    if (Test-Path $envFile) {
        return
    }
    if (-not (Test-Path $example)) {
        throw "Missing .env and .env.example"
    }
    Write-Step "Copying .env.example -> .env"
    Copy-Item $example $envFile
    Write-WarnStep "Edit .env and set LONES_VDL_API_TOKEN before using the UI."
}

function Ensure-WebDeps {
    Assert-Command "node"
    Assert-Command "npm"
    $modules = Join-Path $Root "web\node_modules"
    if (Test-Path $modules) {
        return
    }
    if (-not $Install) {
        throw "Missing web\node_modules. Fix with: powershell -File scripts\dev.ps1 -Install"
    }
    Write-Step "npm install (web)"
    Push-Location (Join-Path $Root "web")
    try {
        npm install
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed"
        }
    }
    finally {
        Pop-Location
    }
}

function Test-ExternalTools {
    if (Get-Command "yt-dlp" -ErrorAction SilentlyContinue) {
        Write-Host "    yt-dlp: OK ($(yt-dlp --version 2>$null))"
    }
    else {
        Write-WarnStep "yt-dlp not on PATH — API will start, but real downloads will fail."
    }
    if (Get-Command "ffmpeg" -ErrorAction SilentlyContinue) {
        Write-Host "    ffmpeg: OK"
    }
    else {
        Write-WarnStep "ffmpeg not on PATH — remux/playback derivatives may fail."
    }
}

function Start-WebTerminal {
    $webDir = Join-Path $Root "web"
    Write-Step "Opening Vite UI in a new terminal (http://127.0.0.1:5173)"
    # Keep this as one line so nested quoting stays simple for Start-Process.
    $command = "Set-Location -LiteralPath '$webDir'; Write-Host 'Lones-VDL web UI (Vite). Proxies /api to http://127.0.0.1:8080' -ForegroundColor Cyan; Write-Host 'Open http://127.0.0.1:5173 and enter LONES_VDL_API_TOKEN from .env' -ForegroundColor Cyan; npm run dev"
    Start-Process -FilePath "powershell.exe" -WorkingDirectory $webDir -ArgumentList @(
        "-NoExit",
        "-NoProfile",
        "-Command",
        $command
    ) | Out-Null
}

function Start-Api([string]$PythonExe) {
    Write-Step "Starting API (http://127.0.0.1:8080) - Ctrl+C stops this process"
    Write-Host "    Health: http://127.0.0.1:8080/api/health"
    Write-Host "    UI:     http://127.0.0.1:5173 (other terminal)"
    & $PythonExe -m lones_vdl serve
}

# --- main ---
if ($ApiOnly -and $WebOnly) {
    throw "Use only one of -ApiOnly / -WebOnly"
}

Write-Step "Repo root: $Root"
$python = Ensure-Venv
Write-Host "    venv python: $python"
Ensure-PythonPackage $python
Ensure-EnvFile

if (-not $ApiOnly) {
    Ensure-WebDeps
}

Write-Step "External tools (optional for downloads/playback)"
Test-ExternalTools

if ($WebOnly) {
    Write-Step "Starting Vite in this terminal"
    Set-Location (Join-Path $Root "web")
    npm run dev
    exit $LASTEXITCODE
}

if (-not $ApiOnly) {
    Start-WebTerminal
    Start-Sleep -Seconds 1
}

Start-Api $python
