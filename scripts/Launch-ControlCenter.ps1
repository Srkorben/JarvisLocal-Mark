[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$LogDirectory = Join-Path $ProjectRoot 'data\control_center'
[System.IO.Directory]::CreateDirectory($LogDirectory) | Out-Null

try {
    if (-not (Test-Path -LiteralPath $Python)) {
        throw 'No existe el entorno .venv de JarvisLocal.'
    }
    & $Python -m jarvis_local.control_center --launch 2>&1 |
        Out-File -LiteralPath (Join-Path $LogDirectory 'desktop-launch.log') -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        throw "El lanzador terminó con código $LASTEXITCODE."
    }
}
catch {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        "No se pudo abrir el Centro de control de JarvisLocal.`n`n$($_.Exception.Message)`n`nRevisa data\control_center\desktop-launch.log.",
        'JarvisLocal',
        [System.Windows.MessageBoxButton]::OK,
        [System.Windows.MessageBoxImage]::Error
    ) | Out-Null
    exit 1
}
