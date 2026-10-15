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
Write-Host "OK: check passed"
