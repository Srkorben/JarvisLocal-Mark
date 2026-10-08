$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
    throw "No existe $python. Ejecuta primero scripts\Setup.ps1."
}

& $python -m jarvis_local.audio_models --root $projectRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
