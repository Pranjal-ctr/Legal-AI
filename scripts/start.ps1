# Kanoon AI: one-command start on Windows (Phase 14).
#
#   .\scripts\start.ps1            build the UI if needed, then serve UI + API at http://127.0.0.1:8000
#   .\scripts\start.ps1 -Rebuild   rebuild the UI first (after frontend changes)
#   .\scripts\start.ps1 -Dev       development mode (auto-reload, /docs); UI dev server: cd frontend; npm run dev
#
# Prerequisites (once): uv sync --extra embed --extra speech; Ollama running with the model
# (ollama pull gemma4:e4b); corpus ingested (python -m scripts.ingest). See README.
param([switch]$Rebuild, [switch]$Dev)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

# Keep temp files and caches on this drive (the system drive may be full).
New-Item -ItemType Directory -Force .tmp | Out-Null
$env:TMP = (Resolve-Path .tmp).Path
$env:TEMP = $env:TMP

# The LLM provider comes from the environment or .env (ADR 0012); Ollama is only needed locally.
$provider = $env:LEGALAI_LLM_PROVIDER
if (-not $provider -and (Test-Path .env)) {
    $line = Select-String -Path .env -Pattern '^\s*LEGALAI_LLM_PROVIDER\s*=\s*(\S+)' | Select-Object -Last 1
    if ($line) { $provider = $line.Matches[0].Groups[1].Value.Trim('"') }
}
if ($provider -eq "gemini") {
    Write-Host "LLM: Gemini API (questions are sent to Google)."
} else {
    try {
        Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 3 | Out-Null
    } catch {
        Write-Warning "Ollama is not reachable on :11434. Start it (ollama serve); until then answers are unavailable."
    }
}

if (-not (Test-Path data/processed/chunks.jsonl)) {
    Write-Host "Ingesting the corpus (first run, ~4 min)..."
    uv run python -m scripts.ingest
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
if (-not (Test-Path data/index/index_meta.json)) {
    Write-Host "Building the search index (first run)..."
    uv run python -m scripts.build_index
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if ($Rebuild -or -not (Test-Path frontend/dist/index.html)) {
    Write-Host "Building the UI..."
    Push-Location frontend
    try {
        if (-not (Test-Path node_modules)) { npm ci; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }
        npm run build
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } finally { Pop-Location }
}

if (-not $Dev) {
    # Production mode: no auto-reload, no /docs, strict CSP. It needs a session key; reuse the
    # development key file (or create one) for this process only. Nothing is written to .env.
    $env:LEGALAI_ENVIRONMENT = "production"
    $hasKey = $env:LEGALAI_SESSION_KEY -or ((Test-Path .env) -and (Select-String -Path .env -Pattern '^\s*LEGALAI_SESSION_KEY=\S' -Quiet))
    if (-not $hasKey) {
        $keyFile = "data/sessions/secret.key"
        if (-not (Test-Path $keyFile)) {
            New-Item -ItemType Directory -Force data/sessions | Out-Null
            uv run python -c "from cryptography.fernet import Fernet; open('$keyFile','wb').write(Fernet.generate_key())"
        }
        $env:LEGALAI_SESSION_KEY = (Get-Content $keyFile -Raw).Trim()
    }
}

Write-Host "Kanoon AI on http://127.0.0.1:8000 (models warm up in the background, ~1-2 min; the status pill shows progress)"
uv run python -m app
