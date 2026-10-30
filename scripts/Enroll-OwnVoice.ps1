[CmdletBinding()]
param(
    [ValidateRange(10, 30)]
    [int]$Seconds = 20
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$ConfigPath = Join-Path $ProjectRoot 'config\jarvis.toml'

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw 'El entorno no está preparado. Ejecuta scripts\Setup.ps1 primero.'
}

& $PythonExe -m jarvis_local.cli `
    --config $ConfigPath `
    --enroll-own-voice `
    --voice-enroll-seconds $Seconds
