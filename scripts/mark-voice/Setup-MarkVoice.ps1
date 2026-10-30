# Instala la voz de Mark (Qwen3-TTS Base 0.6B) en un entorno Python aislado.
# Uso:  pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\mark-voice\Setup-MarkVoice.ps1
[CmdletBinding()]
param(
    [string]$Python312 = (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
    [switch]$Cpu
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$ConfigDir = if ($env:OPENJARVIS_HOME) { $env:OPENJARVIS_HOME } else { Join-Path $HOME '.openjarvis' }
$VoiceHome = Join-Path $ConfigDir 'mark-voice'
$VenvPath = Join-Path $VoiceHome '.venv'
$PythonExe = Join-Path $VenvPath 'Scripts\python.exe'
$ModelPath = Join-Path $VoiceHome 'models\qwen3-tts-12hz-0.6b-base'
$ModelRevision = '5d83992436eae1d760afd27aff78a71d676296fc'

if (-not (Test-Path -LiteralPath $Python312)) {
    throw "Python 3.12 no está instalado en $Python312 (usa -Python312 <ruta>)"
}

Write-Host 'Qwen3-TTS y Qwen3-TTS-12Hz-0.6B-Base usan Apache-2.0:'
Write-Host 'https://github.com/QwenLM/Qwen3-TTS'
Write-Host 'https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base'

New-Item -ItemType Directory -Force -Path $VoiceHome | Out-Null
if (-not (Test-Path -LiteralPath $VenvPath)) {
    & $Python312 -m venv $VenvPath
}

& $PythonExe -m pip install --upgrade pip setuptools wheel
if ($Cpu) {
    & $PythonExe -m pip install torch==2.9.1 torchaudio==2.9.1 --index-url https://download.pytorch.org/whl/cpu
} else {
    & $PythonExe -m pip install torch==2.9.1+cu128 torchaudio==2.9.1+cu128 --index-url https://download.pytorch.org/whl/cu128
}
& $PythonExe -m pip install qwen-tts==0.1.1 transformers==4.57.3 huggingface-hub==0.36.2 numpy

$allowPatterns = "['config.json','generation_config.json','merges.txt','model.safetensors','preprocessor_config.json','README.md','tokenizer_config.json','vocab.json','speech_tokenizer/*']"
$download = "from huggingface_hub import snapshot_download; snapshot_download(repo_id='Qwen/Qwen3-TTS-12Hz-0.6B-Base', revision='$ModelRevision', local_dir=r'$ModelPath', allow_patterns=$allowPatterns)"
$env:HF_HUB_DISABLE_TELEMETRY = '1'
& $PythonExe -c $download

if (-not $Cpu) {
    & $PythonExe -c "import torch; from qwen_tts import Qwen3TTSModel; assert torch.cuda.is_available(); print(torch.__version__, torch.cuda.get_device_name(0))"
}

Write-Host "Voz de Mark instalada en $VoiceHome."
Write-Host 'Siguiente paso: scripts\mark-voice\Enroll-MarkVoice.ps1 para ligar la muestra de voz.'
