[CmdletBinding()]
param(
    [switch]$SmokeTest
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EndpointPath = Join-Path $ProjectRoot 'data\control_center\endpoint.json'
$GodotProject = Join-Path $ProjectRoot 'integrations\godot\mark-presence'
$Godot = if ($SmokeTest) {
    (Get-Command godot_console.exe -ErrorAction Stop).Source
} else {
    (Get-Command godot.exe -ErrorAction Stop).Source
}

if (-not (Test-Path -LiteralPath $EndpointPath)) {
    throw 'Mark Scout no está iniciado. Abre primero la aplicación principal.'
}
$Endpoint = Get-Content -LiteralPath $EndpointPath -Raw | ConvertFrom-Json
if ($Endpoint.bind -ne '127.0.0.1' -or $Endpoint.port -notin 1..65535 -or
    [string]::IsNullOrWhiteSpace([string]$Endpoint.token)) {
    throw 'El endpoint local de Mark Scout no es válido.'
}

$env:MARK_CONTROL_CENTER_URL = "http://127.0.0.1:$($Endpoint.port)"
$env:MARK_CONTROL_CENTER_TOKEN = [string]$Endpoint.token
try {
    if ($SmokeTest) {
        & $Godot --headless --path $GodotProject --rendering-method gl_compatibility -- --smoke-test
        if ($LASTEXITCODE -ne 0) {
            throw "Godot terminó con código $LASTEXITCODE."
        }
    } else {
        $Process = Start-Process -FilePath $Godot -ArgumentList @(
            '--path', "`"$GodotProject`"", '--rendering-method', 'gl_compatibility'
        ) -PassThru -Wait
        if ($Process.ExitCode -ne 0) {
            throw "Godot terminó con código $($Process.ExitCode)."
        }
    }
} finally {
    Remove-Item Env:MARK_CONTROL_CENTER_URL -ErrorAction SilentlyContinue
    Remove-Item Env:MARK_CONTROL_CENTER_TOKEN -ErrorAction SilentlyContinue
}
