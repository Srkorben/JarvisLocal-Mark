# Liga una muestra de voz (15–30 s) y su transcripción literal a la voz de Mark.
# Por defecto usa la muestra versionada en voice\mark_modelo_de voz1.mp3.
[CmdletBinding()]
param(
    [string]$Reference = (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'voice\mark_modelo_de voz1.mp3'),
    [Parameter(Mandatory = $true)]
    [string]$TextFile
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$answer = Read-Host '¿Confirmas que la muestra es tu propia voz o que tienes autorización de su titular? (si/no)'
if ($answer -notin @('si', 'sí', 's')) {
    throw 'Enrolamiento cancelado: se requiere confirmación explícita.'
}

uv run python -m openjarvis.speech.mark_voice enroll `
    --reference $Reference `
    --text-file $TextFile `
    --confirm-own-voice
