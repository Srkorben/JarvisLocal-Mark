[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$ConfigPath = Join-Path $ProjectRoot 'config\jarvis.toml'

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw 'El entorno no está preparado. Ejecuta scripts\Setup.ps1 primero.'
}

Write-Host 'Mark Scout por voz' -ForegroundColor Cyan
Write-Host 'Mantén Ctrl+Alt+M para hablar. Ctrl+Alt+Pause cancela el turno.'
& $PythonExe -m jarvis_local.cli --config $ConfigPath --voice
