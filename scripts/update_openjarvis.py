"""Trae a Mark los cambios nuevos de OpenJarvis sin pisar los de Mark.

OpenJarvis vive copiado dentro de este repositorio (sin historial común), así
que un ``git merge`` no sirve. Este script toma el diff de OpenJarvis entre la
versión base registrada en ``OPENJARVIS_UPSTREAM`` y la versión nueva, y lo
aplica con fusión de tres vías (``git apply --3way``): lo que Mark no tocó se
actualiza tal cual y lo que ambos cambiaron se fusiona o queda marcado como
conflicto para revisarlo.

Uso (desde la raíz del repositorio, con el árbol de trabajo limpio):

    python scripts/update_openjarvis.py            # aplica hasta main
    python scripts/update_openjarvis.py --check    # solo comprueba
    python scripts/update_openjarvis.py --to <commit-o-rama>

Después: ``uv lock``, las pruebas y ``Crear-Acceso-Directo-Mark.bat`` (vuelve a
compilar la interfaz si cambió). Revisa el resultado con ``git diff --cached``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "OPENJARVIS_UPSTREAM"
REFS = "refs/openjarvis"

# Partes de OpenJarvis que Mark sustituyó a propósito: sus workflows de
# publicación (Mark tiene los suyos) y el lockfile, que se regenera con
# ``uv lock`` después de fusionar pyproject.toml.
EXCLUDED = (
    ".github",
    "tests/deployment/test_release_artifact_validation.py",
    "uv.lock",
)


def git(*args: str, check: bool = True, capture: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if check and result.returncode != 0:
        raise SystemExit(
            f"git {' '.join(args)} falló:\n{result.stderr or result.stdout}"
        )
    return (result.stdout or "").strip()


def read_state() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in STATE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    if not values.get("repo") or not values.get("commit"):
        raise SystemExit(f"{STATE_FILE.name} debe tener 'repo=' y 'commit='.")
    return values


def write_state(repo: str, commit: str) -> None:
    STATE_FILE.write_text(
        "# Versión de OpenJarvis integrada en Mark "
        "(la usa scripts/update_openjarvis.py)\n"
        f"repo={repo}\ncommit={commit}\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--to", default="main", help="Rama o commit de OpenJarvis (main)"
    )
    parser.add_argument(
        "--repo", help="Repositorio de OpenJarvis (por defecto, el registrado)"
    )
    parser.add_argument(
        "--check", action="store_true", help="Solo comprueba, no aplica"
    )
    args = parser.parse_args(argv)

    state = read_state()
    repo, base = args.repo or state["repo"], state["commit"]
    if git("status", "--porcelain"):
        raise SystemExit(
            "El árbol de trabajo tiene cambios: haz commit o guárdalos antes."
        )

    print(f"Descargando OpenJarvis ({args.to}) desde {repo}…")
    # Solo hacen falta los dos árboles: profundidad 1, a referencias propias.
    for ref, rev in (("base", base), ("target", args.to)):
        git("fetch", "--quiet", "--no-tags", "--depth=1", repo, f"+{rev}:{REFS}/{ref}")
    target = git("rev-parse", f"{REFS}/target")
    if target == base:
        print(f"Mark ya integra la última versión de OpenJarvis ({base[:7]}).")
        return 0
    print(f"Cambios de OpenJarvis {base[:7]} → {target[:7]}.")

    excludes = [f":(exclude){path}" for path in EXCLUDED]
    patch = git(
        "diff", "--binary", "--full-index", f"{REFS}/base", target, "--", ".", *excludes
    )
    if not patch:
        print("No hay cambios aplicables fuera de las rutas excluidas.")
        if not args.check:
            write_state(repo, target)
        return 0

    with tempfile.NamedTemporaryFile(
        "w", suffix=".patch", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(patch + "\n")
        patch_path = handle.name
    try:
        if args.check:
            result = subprocess.run(
                ["git", "apply", "--3way", "--check", patch_path],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            print(result.stdout + result.stderr)
            print(
                "Comprobación correcta."
                if result.returncode == 0
                else "Habría conflictos."
            )
            return result.returncode
        result = subprocess.run(
            ["git", "apply", "--3way", "--index", patch_path],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        print((result.stdout + result.stderr).strip())
    finally:
        Path(patch_path).unlink(missing_ok=True)

    conflicts = git("diff", "--name-only", "--diff-filter=U", check=False)
    if result.returncode != 0 or conflicts:
        print("\nHay conflictos que revisar (marcados con <<<<<<<):")
        print(conflicts or "(ver mensajes anteriores)")
        print(
            f"Cuando estén resueltos: python {Path(__file__).name} --mark-done {target}"
        )
        return 1
    write_state(repo, target)
    git("add", STATE_FILE.name)
    print(
        f"\nOpenJarvis actualizado a {target[:7]} (cambios en el índice, sin commit).\n"
        "Siguiente: uv lock, pruebas y Crear-Acceso-Directo-Mark.bat."
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--mark-done":
        state = read_state()
        write_state(state["repo"], git("rev-parse", sys.argv[2]))
        print("Versión base actualizada.")
        raise SystemExit(0)
    raise SystemExit(main())
