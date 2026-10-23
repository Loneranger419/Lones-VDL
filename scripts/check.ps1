# Single verification entry point (Windows). Mirrors scripts/check.sh.
#   powershell -File scripts/check.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
# A stale VIRTUAL_ENV (e.g. from an editor) makes uv warn; the project env is backend/.venv.
Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue

function Invoke-Step([string]$Label, [string]$Dir, [scriptblock]$Action) {
    Write-Host "==> $Label"
    Push-Location (Join-Path $root $Dir)
    try {
        & $Action
        if ($LASTEXITCODE -ne 0) { throw "Step failed: $Label (exit $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
}

Invoke-Step "backend: sync" backend { uv sync --locked --quiet }
Invoke-Step "backend: ruff check" backend { uv run ruff check . }
Invoke-Step "backend: ruff format" backend { uv run ruff format --check . }
Invoke-Step "backend: pytest" backend { uv run pytest -q }

if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
    Invoke-Step "frontend: npm ci" frontend { npm ci }
}
Invoke-Step "frontend: prettier" frontend { npm run lint }
Invoke-Step "frontend: svelte-check" frontend { npm run check }
Invoke-Step "frontend: build" frontend { npm run build }

Write-Host "OK: all checks passed"
