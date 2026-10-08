from __future__ import annotations

import argparse
import json

from .launcher import health, launch, project_root, read_endpoint, serve, stop


def main() -> int:
    parser = argparse.ArgumentParser(description="Centro de control local de JarvisLocal")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--launch", action="store_true", help="inicia/reutiliza y abre el panel")
    mode.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    mode.add_argument("--status", action="store_true", help="muestra el endpoint local")
    mode.add_argument("--stop", action="store_true", help="detiene únicamente el panel web")
    parser.add_argument("--no-browser", action="store_true", help="no abre el navegador")
    args = parser.parse_args()
    if args.serve:
        return serve()
    if args.stop:
        print("Centro de control detenido." if stop() else "El centro de control no estaba activo.")
        return 0
    if args.status:
        endpoint = read_endpoint(project_root())
        public_endpoint = None
        if endpoint is not None:
            public_endpoint = {
                key: value for key, value in endpoint.items() if key != "token"
            }
        result = {
            "running": bool(endpoint and health(endpoint)),
            "endpoint": public_endpoint,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["running"] else 1
    result = launch(open_browser=not args.no_browser)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
