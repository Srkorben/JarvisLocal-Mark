from __future__ import annotations

import argparse
from pathlib import Path


WHISPER_REPOSITORY = "Systran/faster-whisper-small"
WHISPER_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
PIPER_REPOSITORY = "rhasspy/piper-voices"
PIPER_REVISION = "c10ece1aade47bb51c153c893d14e5bf8e5b7117"
PIPER_PATTERN = "es/es_MX/ald/medium/*"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Descarga exactamente los dos modelos locales aprobados para Fase 2"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit("Instala primero el extra audio: pip install -e '.[audio]'") from exc

    whisper = root / "models" / "faster-whisper-small"
    piper = root / "models" / "piper"
    snapshot_download(
        repo_id=WHISPER_REPOSITORY,
        revision=WHISPER_REVISION,
        local_dir=whisper,
        allow_patterns=(
            "model.bin",
            "config.json",
            "tokenizer.json",
            "vocabulary.txt",
            "README.md",
            ".gitattributes",
        ),
    )
    snapshot_download(
        repo_id=PIPER_REPOSITORY,
        revision=PIPER_REVISION,
        local_dir=piper,
        allow_patterns=(PIPER_PATTERN,),
    )
    print(f"Whisper: {whisper}")
    print(f"Piper: {piper / 'es' / 'es_MX' / 'ald' / 'medium'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
