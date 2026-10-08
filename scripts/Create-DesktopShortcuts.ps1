[CmdletBinding()]
param()

# Compatibilidad con el nombre histórico. La consolidación sustituyó los nueve
# accesos independientes; no deben recrearse porque volverían a fragmentar el
# escritorio y eludirían el control de instancia del Centro de control.
$Consolidator = Join-Path $PSScriptRoot 'Consolidate-DesktopShortcuts.ps1'
if (-not (Test-Path -LiteralPath $Consolidator)) {
    throw "No existe el consolidador requerido: $Consolidator"
}
Write-Host 'Los accesos individuales fueron sustituidos por JarvisLocal.lnk.'
& $Consolidator
