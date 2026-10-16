from __future__ import annotations

import argparse
import os
from pathlib import Path


BASE_REPOSITORY = "ResembleAI/chatterbox"
BASE_REVISION = "5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18"
LATAM_REPOSITORY = "ResembleAI/Chatterbox-Multilingual-es-mx-latam"
LATAM_REVISION = "27e595bf2fe7be0533ca299d9afafcde08b7cca7"
# s3gen_v3.pt es el decodificador publicado junto al T3 LatAm del Single
# Language Pack V3 (mismo SHA-256 en ambos repositorios). s3gen.pt se conserva
# para poder volver a la combinación anterior desde la configuración.
BASE_FILES = (
    "ve.pt",
    "s3gen.pt",
    "s3gen_v3.pt",
    "grapheme_mtl_merged_expanded_v1.json",
)
LATAM_FILES = ("t3_es_mx_latam.safetensors",)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Descarga los archivos mínimos fijados de Chatterbox LatAm"
    )
    parser.add_argument("--destination", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit("huggingface_hub no está instalado en el entorno aislado") from exc
    snapshot_download(
        repo_id=BASE_REPOSITORY,
        revision=BASE_REVISION,
        local_dir=destination,
        allow_patterns=BASE_FILES,
    )
    snapshot_download(
        repo_id=LATAM_REPOSITORY,
        revision=LATAM_REVISION,
        local_dir=destination,
        allow_patterns=LATAM_FILES,
    )
    # Chatterbox construye siempre el tokenizador multilingüe y spacy-pkuseg
    # intentaría descargar este recurso durante el primer uso. Lo materializamos
    # aquí, con el SHA-256 publicado por la propia dependencia, para que el
    # worker pueda ejecutarse con red deshabilitada después de la instalación.
    pkuseg_home = destination / "pkuseg"
    os.environ["PKUSEG_HOME"] = str(pkuseg_home)
    from spacy_pkuseg.config import Config
    from spacy_pkuseg.download import download_model

    pkuseg = Config()
    download_model(
        pkuseg.model_urls["spacy_ontonotes"],
        str(pkuseg_home),
        pkuseg.model_hash["spacy_ontonotes"],
    )
    print(f"Modelo Chatterbox LatAm fijado en: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
