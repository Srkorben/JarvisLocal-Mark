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

Write-Host '=== Núcleo, modelos y almacenamiento ===' -ForegroundColor Cyan
& $PythonExe -m jarvis_local.cli --config $ConfigPath --doctor
$CoreExit = $LASTEXITCODE

Write-Host "`n=== Cadena de auditoría ===" -ForegroundColor Cyan
& $PythonExe -m jarvis_local.cli --config $ConfigPath --verify-audit
$AuditExit = $LASTEXITCODE

Write-Host "`n=== Dispositivos y modelos de voz ===" -ForegroundColor Cyan
& $PythonExe -m jarvis_local.cli --config $ConfigPath --audio-doctor
$AudioExit = $LASTEXITCODE

Write-Host "`nResultados: núcleo=$CoreExit, auditoría=$AuditExit, audio=$AudioExit"
if ($AudioExit -ne 0) {
    Write-Host 'Si falta reference.wav, utiliza el acceso «Enrolar mi voz».' -ForegroundColor Yellow
}
