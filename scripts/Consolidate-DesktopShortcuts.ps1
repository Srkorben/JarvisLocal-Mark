[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Desktop = [Environment]::GetFolderPath('Desktop')
$DesktopApp = Join-Path $ProjectRoot 'runtime\desktop\JarvisLocal.exe'
$Icon = Join-Path $ProjectRoot 'assets\mark-scout.ico'
$CentralShortcut = Join-Path $Desktop 'Mark Scout.lnk'
$Names = @(
    'JarvisLocal.lnk',
    'JarvisLocal - Abrir proyecto.lnk',
    'JarvisLocal - Chat de texto.lnk',
    'JarvisLocal - Configuración.lnk',
    'JarvisLocal - Conversación por voz.lnk',
    'JarvisLocal - Diagnóstico.lnk',
    'JarvisLocal - Enrolar mi voz.lnk',
    'JarvisLocal - Instalar o reparar.lnk',
    'JarvisLocal - Preparar clonación de voz.lnk',
    'JarvisLocal - Preparar modelos de audio.lnk'
)

foreach ($Required in @($DesktopApp, $Icon)) {
    if (-not (Test-Path -LiteralPath $Required)) {
        throw "Falta el archivo requerido: $Required"
    }
}

$Shell = New-Object -ComObject WScript.Shell
$Existing = $Names | ForEach-Object { Join-Path $Desktop $_ } | Where-Object { Test-Path -LiteralPath $_ }
if ($Existing.Count -gt 0) {
    $Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $Backup = Join-Path $ProjectRoot "backups\desktop-shortcuts\$Stamp"
    [System.IO.Directory]::CreateDirectory($Backup) | Out-Null
    $Inventory = foreach ($Path in $Existing) {
        $Link = $Shell.CreateShortcut($Path)
        Copy-Item -LiteralPath $Path -Destination $Backup
        [pscustomobject]@{
            name = [System.IO.Path]::GetFileName($Path)
            target = $Link.TargetPath
            arguments = $Link.Arguments
            working_directory = $Link.WorkingDirectory
            description = $Link.Description
            icon = $Link.IconLocation
        }
    }
    $Inventory | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Backup 'inventory.json') -Encoding utf8
}

$Shortcut = $Shell.CreateShortcut($CentralShortcut)
$Shortcut.TargetPath = $DesktopApp
$Shortcut.Arguments = ''
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.Description = 'Abre Mark Scout, el asistente local de escritorio.'
$Shortcut.IconLocation = "$Icon,0"
$Shortcut.WindowStyle = 1
$Shortcut.Save()

$Validation = $Shell.CreateShortcut($CentralShortcut)
if ($Validation.TargetPath -ne $DesktopApp -or -not (Test-Path -LiteralPath $Icon)) {
    throw 'El acceso central no superó la validación; no se retiraron los anteriores.'
}

foreach ($Path in $Existing) {
    Remove-Item -LiteralPath $Path
}
Write-Host "Acceso único creado: $CentralShortcut"
Write-Host "Accesos sustituidos y respaldados: $($Existing.Count)"
