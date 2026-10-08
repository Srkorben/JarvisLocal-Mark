[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python312 = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
$VenvPath = Join-Path $ProjectRoot '.venv-chatterbox'
$PythonExe = Join-Path $VenvPath 'Scripts\python.exe'
$ModelPath = Join-Path $ProjectRoot 'models\chatterbox-es-latam'
$ChatterboxCommit = '5de7a54aa4e5e2baadb0182dde554908b48b85c2'
$PerthCommit = 'ff1c8ac55a976971245cdd53c18d6131ca00d993'

if (-not (Test-Path -LiteralPath $Python312)) {
    throw "Python 3.12 no está instalado en $Python312"
}

$drive = Get-PSDrive -Name ([System.IO.Path]::GetPathRoot($ProjectRoot).TrimEnd(':','\'))
if ($drive.Free -lt 10GB) {
    throw 'Se requieren al menos 10 GiB libres para entorno, caché y modelo.'
}

if (-not (Test-Path -LiteralPath $VenvPath)) {
    & $Python312 -m venv $VenvPath
}

& $PythonExe -m pip install --upgrade pip setuptools
& $PythonExe -m pip install "git+https://github.com/resemble-ai/Perth.git@$PerthCommit"
& $PythonExe -m pip install "git+https://github.com/resemble-ai/chatterbox.git@$ChatterboxCommit"
& $PythonExe -m pip install --editable $ProjectRoot --no-deps
& $PythonExe -m jarvis_local.voice_clone_models --destination $ModelPath

Write-Host 'Chatterbox quedó instalado de forma aislada y en CPU por defecto.'
Write-Host 'El backend seguirá bloqueado hasta enrolar explícitamente tu propia voz.'
