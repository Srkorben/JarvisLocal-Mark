#!/usr/bin/env bash
# Instala la voz de Mark (Qwen3-TTS Base 0.6B) en un entorno Python aislado.
# Uso: scripts/mark-voice/setup-mark-voice.sh [--cpu]
set -euo pipefail

CONFIG_DIR="${OPENJARVIS_HOME:-$HOME/.openjarvis}"
VOICE_HOME="$CONFIG_DIR/mark-voice"
VENV="$VOICE_HOME/.venv"
MODEL_PATH="$VOICE_HOME/models/qwen3-tts-12hz-0.6b-base"
MODEL_REVISION="5d83992436eae1d760afd27aff78a71d676296fc"
PYTHON="${PYTHON:-python3.12}"

mkdir -p "$VOICE_HOME"
[ -x "$VENV/bin/python" ] || "$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip setuptools wheel
if [ "${1:-}" = "--cpu" ]; then
  "$VENV/bin/python" -m pip install torch==2.9.1 torchaudio==2.9.1 \
    --index-url https://download.pytorch.org/whl/cpu
else
  "$VENV/bin/python" -m pip install torch==2.9.1 torchaudio==2.9.1 \
    --index-url https://download.pytorch.org/whl/cu128
fi
"$VENV/bin/python" -m pip install qwen-tts==0.1.1 transformers==4.57.3 \
  huggingface-hub==0.36.2 numpy

HF_HUB_DISABLE_TELEMETRY=1 "$VENV/bin/python" - "$MODEL_PATH" "$MODEL_REVISION" <<'PY'
import sys
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    revision=sys.argv[2],
    local_dir=sys.argv[1],
    allow_patterns=[
        "config.json", "generation_config.json", "merges.txt",
        "model.safetensors", "preprocessor_config.json", "README.md",
        "tokenizer_config.json", "vocab.json", "speech_tokenizer/*",
    ],
)
PY

echo "Voz de Mark instalada en $VOICE_HOME."
echo "Siguiente paso:"
echo "  uv run python -m openjarvis.speech.mark_voice enroll \\"
echo "    --reference 'voice/mark_modelo_de voz1.mp3' --text-file transcripcion.txt \\"
echo "    --confirm-own-voice"
