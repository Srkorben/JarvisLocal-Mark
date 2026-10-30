<#
.SYNOPSIS
    Instala o actualiza Mark (con su upgrade OpenJarvis) en Windows.

.DESCRIPTION
    Lo ejecuta Crear-Acceso-Directo-Mark.bat. Reutiliza todo lo que ya exista y
    nunca toca data\, models\, runtime\ (salvo republicar el ejecutable) ni los
    entornos aislados de voz. Pasos:
      1. Cierra solo los procesos de Mark (su .venv y su JarvisLocal.exe).
      2. uv y dependencias de Python 3.12, incluido el componente Rust de
         OpenJarvis (requiere MSVC Build Tools; pide permiso para instalarlas).
      3. Compila la interfaz de OpenJarvis cuando cambia (Node.js).
      4. Ollama corriendo (oculto) con el modelo de Mark.
      5. Publica JarvisLocal.exe cuando su código cambia (.NET 8 SDK).
      6. Crea o actualiza el acceso directo "Mark" del escritorio.
    Deja un registro en data\logs\install-<fecha>.log.

.PARAMETER Yes
    Acepta sin preguntar las instalaciones grandes (Build Tools, .NET SDK).
#>
[CmdletBinding()]
param(
    [switch]$Yes,
    [string]$Model = 'qwen3:8b'
)

# 'Continue': en Windows PowerShell 5.1, con 'Stop' la salida de error de un
# programa externo redirigida (2>$null) se vuelve un error fatal. Cada paso
# comprueba $LASTEXITCODE de forma explícita.
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root 'data\logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir ('install-{0:yyyyMMdd-HHmmss}.log' -f (Get-Date))
Start-Transcript -Path $LogFile | Out-Null

$Report = [ordered]@{}
function Step([string]$Title) { Write-Host ''; Write-Host "== $Title" -ForegroundColor Cyan }
function Ok([string]$Key, [string]$Text) { $Report[$Key] = "OK     $Text"; Write-Host "   OK     $Text" -ForegroundColor Green }
function Warn([string]$Key, [string]$Text) { $Report[$Key] = "AVISO  $Text"; Write-Host "   AVISO  $Text" -ForegroundColor Yellow }
function Bad([string]$Key, [string]$Text) { $Report[$Key] = "ERROR  $Text"; Write-Host "   ERROR  $Text" -ForegroundColor Red }
function Have([string]$Name) { return [bool](Get-Command $Name -ErrorAction SilentlyContinue) }
function Ask([string]$Question) {
    if ($Yes) { return $true }
    $answer = Read-Host "$Question [S/n]"
    return ($answer -eq '' -or $answer -match '^(s|si|sí|y|yes)$')
}
function Update-SessionPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user;$(Join-Path $HOME '.local\bin')"
}
function Install-WithWinget([string]$Id, [string[]]$Extra = @()) {
    if (-not (Have 'winget')) { return $false }
    $wingetArgs = @('install', '-e', '--id', $Id, '--accept-source-agreements', '--accept-package-agreements') + $Extra
    & winget @wingetArgs
    $code = $LASTEXITCODE
    Update-SessionPath
    return ($code -eq 0)
}
function Get-TreeId([string]$Path) {
    if (-not (Have 'git')) { return '' }
    $id = & git -C $Root rev-parse "HEAD:$Path" 2>$null
    if ($LASTEXITCODE -ne 0) { return '' }
    return "$id".Trim()
}
function Read-Stamp([string]$File) {
    if (Test-Path -LiteralPath $File) { return (Get-Content -LiteralPath $File -Raw).Trim() }
    return ''
}

# Copiado del instalador oficial de OpenJarvis (deploy\windows\install.ps1).
function Test-MsvcLinker {
    foreach ($cmd in @(Get-Command link.exe -All -CommandType Application -ErrorAction SilentlyContinue)) {
        $item = Get-Item -LiteralPath $cmd.Source -ErrorAction SilentlyContinue
        if ($item -and $item.VersionInfo.CompanyName -match '^Microsoft' -and
            $item.VersionInfo.OriginalFilename -ieq 'link.exe') { return $true }
    }
    if (-not ${env:ProgramFiles(x86)}) { return $false }
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswhere)) { return $false }
    $found = & $vswhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -find 'VC\Tools\MSVC\**\bin\Host*\*\link.exe' 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    foreach ($linker in $found) { if (Test-Path -LiteralPath $linker -PathType Leaf) { return $true } }
    return $false
}

$Python = Join-Path $Root '.venv\Scripts\python.exe'
$DesktopExe = Join-Path $Root 'runtime\desktop\JarvisLocal.exe'
Push-Location $Root
try {
    # ------------------------------------------------------------------ 1
    Step 'Cerrando Mark si está abierto'
    $venvPrefix = (Join-Path $Root '.venv') + '\'
    $all = @(Get-CimInstance Win32_Process)
    $ids = @($all | Where-Object {
            $_.ExecutablePath -and (
                $_.ExecutablePath.StartsWith($venvPrefix, [StringComparison]::OrdinalIgnoreCase) -or
                $_.ExecutablePath -ieq $DesktopExe)
        } | ForEach-Object { $_.ProcessId })
    do {
        $count = $ids.Count
        $children = @($all | Where-Object { $ids -contains $_.ParentProcessId } | ForEach-Object { $_.ProcessId })
        $ids = @(($ids + $children) | Select-Object -Unique)
    } while ($ids.Count -gt $count)
    # Ollama puede haber sido iniciado por Mark, pero es un servicio aparte: no se cierra.
    $targets = @($all | Where-Object { ($ids -contains $_.ProcessId) -and ($_.Name -notmatch '^ollama') })
    foreach ($process in $targets) {
        Write-Host "   Cerrando $($process.Name) (PID $($process.ProcessId))"
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
    if ($targets.Count) { Start-Sleep -Seconds 2 }
    Ok 'procesos' "$($targets.Count) procesos de Mark cerrados"

    # ------------------------------------------------------------------ 2
    Step 'Python y dependencias (uv)'
    if (-not (Have 'uv')) {
        Write-Host '   Instalando uv...'
        powershell -NoProfile -ExecutionPolicy Bypass -Command 'irm https://astral.sh/uv/install.ps1 | iex'
        Update-SessionPath
    }
    if (-not (Have 'uv')) { throw 'No se pudo instalar uv. Instálalo desde https://docs.astral.sh/uv/ y repite.' }

    $native = Test-MsvcLinker
    if (-not $native) {
        Write-Host '   El componente Rust de OpenJarvis (herramientas, memoria y seguridad de los'
        Write-Host '   agentes) se compila con las MSVC Build Tools, que no están instaladas.'
        if (Ask '   ¿Instalarlas ahora? (descarga de varios GB; Windows pedirá permiso)') {
            [void](Install-WithWinget 'Microsoft.VisualStudio.2022.BuildTools' @(
                    '--override', '--wait --quiet --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended'))
            $native = Test-MsvcLinker
        }
    }
    $syncArgs = @('sync', '--extra', 'mark-audio', '--extra', 'desktop')
    if ($native) { $syncArgs += @('--group', 'desktop-native') }
    & uv @syncArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host '   Reintentando en 5 segundos...'
        Start-Sleep -Seconds 5
        & uv @syncArgs
    }
    if ($LASTEXITCODE -ne 0 -and $native) {
        Write-Host '   Falló la compilación nativa; se instala sin el componente Rust.'
        $native = $false
        & uv sync --extra mark-audio --extra desktop
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Python)) {
        throw 'No se pudieron instalar las dependencias de Mark. Si algún archivo sigue en uso, reinicia el PC y repite.'
    }
    & $Python -c 'import jarvis_local, openjarvis' 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'El entorno de Mark quedó incompleto (no importa jarvis_local/openjarvis).' }
    Ok 'python' 'Entorno de Mark listo (.venv, Python 3.12)'
    & $Python -c 'import openjarvis_rust' 2>$null
    if ($LASTEXITCODE -eq 0) {
        Ok 'rust' 'Componente Rust de OpenJarvis instalado'
    } else {
        Warn 'rust' 'Sin componente Rust: herramientas y memoria de los agentes de OpenJarvis no funcionarán'
    }

    # ------------------------------------------------------------------ 2b
    Step 'Voz de Mark Scout (solo comprobación, no modifica nada)'
    $voiceJson = (& $Python -m jarvis_local.control_center --voice-check 2>$null) -join "`n"
    try { $voice = $voiceJson | ConvertFrom-Json } catch { $voice = $null }
    if (-not $voice) {
        Bad 'voz' 'No se pudo comprobar la voz (ver registro)'
    } else {
        Write-Host "   Motor de voz: $($voice.tts_provider) ($($voice.tts_device)); referencia: $($voice.reference)"
        $qwenPython = Join-Path $Root '.venv-qwen3-tts\Scripts\python.exe'
        $workerOk = $true
        if ($voice.tts_provider -eq 'qwen3_tts' -and (Test-Path -LiteralPath $qwenPython)) {
            & $qwenPython -c 'import jarvis_local.qwen3_tts_worker' 2>$null
            $workerOk = ($LASTEXITCODE -eq 0)
        }
        if ($voice.ready -and $workerOk) {
            Ok 'voz' 'Voz de Mark Scout lista: Iniciar llamada disponible'
        } elseif (-not $workerOk) {
            Warn 'voz' 'El entorno .venv-qwen3-tts no carga el worker de voz: ejecuta scripts\Setup-Qwen3TTS.ps1'
        } else {
            Warn 'voz' ('Iniciar llamada no disponible. Falta: ' + (@($voice.missing) -join '; '))
        }
    }

    # ------------------------------------------------------------------ 3
    Step 'Interfaz de capacidades (OpenJarvis)'
    $uiIndex = Join-Path $Root 'src\openjarvis\server\static\index.html'
    $uiStamp = Join-Path $Root 'src\openjarvis\server\static\.mark-build'
    $uiTree = Get-TreeId 'frontend'
    if ((Test-Path -LiteralPath $uiIndex) -and $uiTree -and ((Read-Stamp $uiStamp) -eq $uiTree)) {
        Ok 'interfaz' 'Interfaz compilada y al día'
    } else {
        if (-not (Have 'npm')) {
            Write-Host '   Instalando Node.js...'
            [void](Install-WithWinget 'OpenJS.NodeJS.LTS')
            $env:Path = "$env:ProgramFiles\nodejs;$env:Path"
        }
        if (-not (Have 'npm')) {
            if (Test-Path -LiteralPath $uiIndex) { Warn 'interfaz' 'Sin Node.js: se mantiene la interfaz compilada anterior' }
            else { Bad 'interfaz' 'Sin Node.js no se puede compilar la interfaz (https://nodejs.org)' }
        } else {
            Push-Location (Join-Path $Root 'frontend')
            try {
                & npx -y npm@11 ci --no-audit --no-fund
                if ($LASTEXITCODE -eq 0) { & npx -y npm@11 run build }
                if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $uiIndex)) {
                    if ($uiTree) { Set-Content -LiteralPath $uiStamp -Value $uiTree -NoNewline }
                    Ok 'interfaz' 'Interfaz compilada'
                } else {
                    Bad 'interfaz' 'Falló la compilación de la interfaz (ver registro)'
                }
            } finally { Pop-Location }
        }
    }

    # ------------------------------------------------------------------ 4
    Step "Ollama y el modelo $Model"
    $ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
    if (-not $ollama) {
        $candidate = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
        if (Test-Path -LiteralPath $candidate) { $ollama = $candidate }
    }
    if (-not $ollama) {
        Write-Host '   Instalando Ollama...'
        [void](Install-WithWinget 'Ollama.Ollama')
        $candidate = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
        if (Test-Path -LiteralPath $candidate) { $ollama = $candidate }
    }
    if (-not $ollama) {
        Bad 'ollama' 'Ollama no está instalado (https://ollama.com)'
    } else {
        $running = $false
        try { Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 3 -ErrorAction Stop | Out-Null; $running = $true } catch { }
        if (-not $running) {
            Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Hidden
            for ($i = 0; $i -lt 20 -and -not $running; $i++) {
                Start-Sleep -Seconds 1
                try { Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 -ErrorAction Stop | Out-Null; $running = $true } catch { }
            }
        }
        $models = (& $ollama list 2>$null) -join "`n"
        if ($models -notmatch "(?m)^$([regex]::Escape($Model))\s") {
            Write-Host "   Descargando $Model (solo la primera vez)..."
            & $ollama pull $Model
        }
        $models = (& $ollama list 2>$null) -join "`n"
        if ($running -and $models -match "(?m)^$([regex]::Escape($Model))\s") { Ok 'ollama' "Ollama listo con $Model" }
        else { Bad 'ollama' "Ollama no responde o falta $Model" }
    }

    # ------------------------------------------------------------------ 5
    Step 'Aplicación de escritorio (JarvisLocal.exe)'
    $exeStamp = Join-Path $Root 'runtime\desktop\.mark-build'
    $exeTree = Get-TreeId 'desktop/JarvisLocal.Desktop'
    $current = (Test-Path -LiteralPath $DesktopExe) -and $exeTree -and ((Read-Stamp $exeStamp) -eq $exeTree)
    if ($current) {
        Ok 'escritorio' 'JarvisLocal.exe al día'
    } else {
        $sdk = (Have 'dotnet') -and (@(& dotnet --list-sdks 2>$null) -match '^8\.').Count -gt 0
        if (-not $sdk -and (Ask '   Para publicar la app hace falta el SDK de .NET 8 (unos cientos de MB). ¿Instalarlo?')) {
            [void](Install-WithWinget 'Microsoft.DotNet.SDK.8')
            $sdk = (Have 'dotnet') -and (@(& dotnet --list-sdks 2>$null) -match '^8\.').Count -gt 0
        }
        $published = $false
        if ($sdk -and (Test-Path -LiteralPath $DesktopExe)) {
            # Copia recuperable de la versión que funcionaba antes de republicar.
            $backup = Join-Path $Root ('backups\desktop-{0:yyyyMMdd-HHmmss}' -f (Get-Date))
            Copy-Item -LiteralPath (Split-Path -Parent $DesktopExe) -Destination $backup -Recurse -Force
            Write-Host "   Copia del ejecutable anterior: $backup"
        }
        if ($sdk) {
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'scripts\Publish-Desktop.ps1')
            $published = ($LASTEXITCODE -eq 0) -and (Test-Path -LiteralPath $DesktopExe)
        }
        if ($published) {
            if ($exeTree) { Set-Content -LiteralPath $exeStamp -Value $exeTree -NoNewline }
            Ok 'escritorio' 'JarvisLocal.exe publicado'
        } elseif (Test-Path -LiteralPath $DesktopExe) {
            Warn 'escritorio' 'Se mantiene el JarvisLocal.exe anterior (sin micrófono en Capacidades)'
        } else {
            Bad 'escritorio' 'Falta JarvisLocal.exe y no se pudo publicar (.NET 8 SDK)'
        }
    }

    # ------------------------------------------------------------------ 6
    Step 'Acceso directo'
    if (Test-Path -LiteralPath $DesktopExe) {
        $desktop = [Environment]::GetFolderPath('Desktop')
        $link = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop 'Mark.lnk'))
        $link.TargetPath = $DesktopExe
        $link.WorkingDirectory = $Root
        $link.IconLocation = (Join-Path $Root 'assets\mark-scout.ico') + ',0'
        $link.Description = 'Mark - asistente personal local'
        $link.Save()
        Ok 'acceso' "Mark.lnk en $desktop"
    } else {
        Bad 'acceso' 'Sin ejecutable no se crea el acceso directo'
    }
} catch {
    Bad 'instalacion' $_.Exception.Message
} finally {
    Pop-Location
}

Write-Host ''
Write-Host '== Resumen' -ForegroundColor Cyan
foreach ($key in $Report.Keys) { Write-Host "   $($Report[$key])" }
Write-Host "   Registro: $LogFile"
Stop-Transcript | Out-Null
$failed = @($Report.Values | Where-Object { $_ -like 'ERROR*' }).Count
if ($failed) { exit 1 }
exit 0
