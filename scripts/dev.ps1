# Quick local run: verify deps, open API + Vite (prefers one Windows Terminal window).
# Usage:
#   powershell -File scripts\dev.ps1
#   powershell -File scripts\dev.ps1 -Install   # create venv / pip / npm if missing
#   powershell -File scripts\dev.ps1 -ApiOnly
#   powershell -File scripts\dev.ps1 -WebOnly
#   powershell -File scripts\dev.ps1 -NoTerminal  # force separate consoles (skip wt.exe)
#
# With Windows Terminal: one window, split panes (API | Vite). In the API pane,
# Ctrl+C then Enter restarts the server without opening a new window.

[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$ApiOnly,
    [switch]$WebOnly,
    [switch]$NoTerminal
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

function Get-WindowsTerminal {
    $cmd = Get-Command "wt.exe" -ErrorAction SilentlyContinue
    if ($null -ne $cmd) {
        return $cmd.Source
    }
    $candidate = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\wt.exe"
    if (Test-Path -LiteralPath $candidate) {
        return $candidate
    }
    return $null
}

function Start-WebFallbackTerminal {
    $webDir = Join-Path $Root "web"
    Write-Step "Opening Vite UI in a new console (http://127.0.0.1:5173)"
    # Keep this as one line so nested quoting stays simple for Start-Process.
    $command = "Set-Location -LiteralPath '$webDir'; Write-Host 'Lone''s VDL web UI (Vite). Proxies /api to http://127.0.0.1:8080' -ForegroundColor Cyan; Write-Host 'Open http://127.0.0.1:5173 and enter LONES_VDL_API_TOKEN from .env' -ForegroundColor Cyan; npm run dev"
    Start-Process -FilePath "powershell.exe" -WorkingDirectory $webDir -ArgumentList @(
        "-NoExit",
        "-NoProfile",
        "-Command",
        $command
    ) | Out-Null
}

function Start-DevWindowsTerminal {
    # One window, vertical split: API (left) | Vite (right). Fixed size/pos so relaunches land predictably.
    $wt = Get-WindowsTerminal
    if ($null -eq $wt) {
        return $false
    }
    $devPs1 = Join-Path $PSScriptRoot "dev.ps1"
    $webDir = Join-Path $Root "web"
    Write-Step "Opening Windows Terminal (API | Vite split)"
    Write-Host "    Restart API: Ctrl+C in the API pane, then press Enter"
    Write-Host "    UI: http://127.0.0.1:5173  ·  API: http://127.0.0.1:8080"
    # Start-Process joins ArgumentList arrays with spaces and breaks paths like
    # "My Documents". Pass one quoted command line instead.
    $argLine = @(
        "--pos", "80,60",
        "--size", "160,48",
        "-w", "new",
        "nt", "--title", "API",
        "-d", "`"$Root`"",
        "powershell", "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", "`"$devPs1`"", "-ApiOnly",
        ";",
        "sp", "-V", "--title", "Vite",
        "-d", "`"$webDir`"",
        "powershell", "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", "`"$devPs1`"", "-WebOnly"
    ) -join " "
    Start-Process -FilePath $wt -WorkingDirectory $Root -ArgumentList $argLine | Out-Null
    return $true
}

function Start-Api([string]$PythonExe) {
    Write-Step "API on http://127.0.0.1:8080"
    Write-Host "    Health: http://127.0.0.1:8080/api/health"
    Write-Host "    UI:     http://127.0.0.1:5173"
    Write-Host "    Restart: Ctrl+C, then Enter (same pane/window)" -ForegroundColor DarkGray
    while ($true) {
        & $PythonExe -m lones_vdl serve
        $code = $LASTEXITCODE
        Write-Host ""
        Write-Host "API stopped (exit $code). Press Enter to restart, or Ctrl+C to quit." -ForegroundColor Yellow
        try {
            [void](Read-Host)
        }
        catch {
            # Non-interactive / Ctrl+C during Read-Host
            break
        }
    }
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
    Write-Step "Starting Vite in this terminal (http://127.0.0.1:5173)"
    Set-Location (Join-Path $Root "web")
    npm run dev
    exit $LASTEXITCODE
}

if (-not $ApiOnly -and -not $NoTerminal) {
    if (Start-DevWindowsTerminal) {
        exit 0
    }
    Write-WarnStep "Windows Terminal (wt.exe) not found; using separate consoles."
}

if (-not $ApiOnly) {
    Start-WebFallbackTerminal
    Start-Sleep -Seconds 1
}

Start-Api $python
