# Windows-friendly verification entry point (same as `make check`).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Invoke-Step([string]$Label, [scriptblock]$Action) {
    Write-Host "==> $Label"
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Label (exit $LASTEXITCODE)"
    }
}

Invoke-Step "ruff check" { python -m ruff check src tests }
Invoke-Step "ruff format --check" { python -m ruff format --check src tests }
Invoke-Step "pytest" { python -m pytest -q }

$webPkg = Join-Path (Get-Location) "web\package.json"
$webModules = Join-Path (Get-Location) "web\node_modules"
if ((Test-Path $webPkg) -and (Test-Path $webModules)) {
    Invoke-Step "web svelte-check" {
        Push-Location web
        try { npm run check } finally { Pop-Location }
    }
}

Write-Host "OK: check passed"
