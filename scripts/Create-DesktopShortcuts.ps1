[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Desktop = [Environment]::GetFolderPath('Desktop')
$PowerShell = (Get-Command pwsh.exe -ErrorAction Stop).Source
$Explorer = Join-Path $env:WINDIR 'explorer.exe'
$Notepad = Join-Path $env:WINDIR 'System32\notepad.exe'
$Shell = New-Object -ComObject WScript.Shell

function New-JarvisShortcut {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [string]$Target,
        [Parameter(Mandatory)] [string]$Arguments,
        [Parameter(Mandatory)] [string]$Description,
        [Parameter(Mandatory)] [string]$Icon
    )

    $Shortcut = $Shell.CreateShortcut((Join-Path $Desktop "$Name.lnk"))
    $Shortcut.TargetPath = $Target
    $Shortcut.Arguments = $Arguments
    $Shortcut.Description = $Description
    $Shortcut.WorkingDirectory = $ProjectRoot
    $Shortcut.IconLocation = $Icon
    $Shortcut.WindowStyle = 1
    $Shortcut.Save()
}

$PowerShellIcon = "$PowerShell,0"
$Definitions = @(
    @('JarvisLocal - Chat de texto', 'Run-Jarvis.ps1', 'Abrir la conversación textual local.'),
    @('JarvisLocal - Conversación por voz', 'Run-Jarvis-Voice.ps1', 'Iniciar voz local con push-to-talk.'),
    @('JarvisLocal - Enrolar mi voz', 'Enroll-OwnVoice.ps1', 'Grabar conscientemente la muestra de voz propia.'),
    @('JarvisLocal - Diagnóstico', 'Diagnose-Jarvis.ps1', 'Comprobar núcleo, auditoría, audio y modelos.'),
    @('JarvisLocal - Instalar o reparar', 'Setup.ps1', 'Recrear y validar las dependencias del núcleo.'),
    @('JarvisLocal - Preparar modelos de audio', 'Setup-AudioModels.ps1', 'Descargar o comprobar los modelos de audio.'),
    @('JarvisLocal - Preparar clonación de voz', 'Setup-VoiceClone.ps1', 'Instalar o comprobar Chatterbox LatAm aislado.')
)

foreach ($Definition in $Definitions) {
    $Script = Join-Path $PSScriptRoot $Definition[1]
    New-JarvisShortcut `
        -Name $Definition[0] `
        -Target $PowerShell `
        -Arguments "-NoExit -NoProfile -ExecutionPolicy Bypass -File `"$Script`"" `
        -Description $Definition[2] `
        -Icon $PowerShellIcon
}

New-JarvisShortcut `
    -Name 'JarvisLocal - Abrir proyecto' `
    -Target $Explorer `
    -Arguments "`"$ProjectRoot`"" `
    -Description 'Abrir la carpeta del proyecto JarvisLocal.' `
    -Icon "$Explorer,0"

New-JarvisShortcut `
    -Name 'JarvisLocal - Configuración' `
    -Target $Notepad `
    -Arguments "`"$(Join-Path $ProjectRoot 'config\jarvis.toml')`"" `
    -Description 'Abrir la configuración local validada.' `
    -Icon "$Notepad,0"

Write-Host "Se crearon 9 accesos directos de JarvisLocal en $Desktop"
