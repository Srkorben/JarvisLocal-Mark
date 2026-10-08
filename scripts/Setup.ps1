[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot '.venv'
$Python312 = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'

if (-not (Test-Path -LiteralPath $Python312)) {
    throw "Python 3.12 no está instalado en $Python312"
}

if (Test-Path -LiteralPath $VenvPath) {
    $ExistingPython = Join-Path $VenvPath 'Scripts\python.exe'
    $ExistingVersion = if (Test-Path -LiteralPath $ExistingPython) {
        (& $ExistingPython -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")').Trim()
    } else {
        'invalid'
    }
    if ($ExistingVersion -ne '3.12') {
        $ResolvedProject = [System.IO.Path]::GetFullPath($ProjectRoot)
        $ResolvedVenv = [System.IO.Path]::GetFullPath($VenvPath)
        if (-not $ResolvedVenv.StartsWith($ResolvedProject, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw 'La ruta del entorno virtual no pertenece al proyecto.'
        }
        $BackupPath = Join-Path $ProjectRoot ('.venv.incompatible-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
        Move-Item -LiteralPath $VenvPath -Destination $BackupPath
        Write-Host "Entorno incompatible preservado en $BackupPath"
    }
}

if (-not (Test-Path -LiteralPath $VenvPath)) {
    & $Python312 -m venv $VenvPath
}

$PythonExe = Join-Path $VenvPath 'Scripts\python.exe'
& $PythonExe -m pip install --upgrade pip setuptools
& $PythonExe -m pip install --editable "${ProjectRoot}[dev]"
& $PythonExe -m pytest -q (Join-Path $ProjectRoot 'tests')
& $PythonExe -m jarvis_local.cli --config (Join-Path $ProjectRoot 'config\jarvis.toml') --doctor

