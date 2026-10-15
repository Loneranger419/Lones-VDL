# Windows-friendly verification entry point (same as `make check`).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "==> ruff check"
python -m ruff check src tests
Write-Host "==> ruff format --check"
python -m ruff format --check src tests
Write-Host "==> pytest"
python -m pytest -q
Write-Host "OK: check passed"
