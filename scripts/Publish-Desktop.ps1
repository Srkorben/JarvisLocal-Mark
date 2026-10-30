[CmdletBinding()]
param(
    [ValidateSet('Release', 'Debug')]
    [string]$Configuration = 'Release'
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$desktopProject = Join-Path $projectRoot 'desktop\JarvisLocal.Desktop\JarvisLocal.Desktop.csproj'
$outputDirectory = Join-Path $projectRoot 'runtime\desktop'

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw 'No se encontró .NET SDK 8. Instálalo antes de publicar JarvisLocal Desktop.'
}

dotnet publish $desktopProject `
    --configuration $Configuration `
    --runtime win-x64 `
    --self-contained false `
    --output $outputDirectory

if ($LASTEXITCODE -ne 0) {
    throw "La publicación de JarvisLocal Desktop terminó con código $LASTEXITCODE."
}

$executable = Join-Path $outputDirectory 'JarvisLocal.exe'
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "La publicación no produjo $executable."
}

Write-Host "JarvisLocal Desktop publicado en: $executable"
