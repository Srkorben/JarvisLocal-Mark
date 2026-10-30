from __future__ import annotations

import http.cookiejar
import json
import re
import urllib.request

from .control_center.launcher import HOST, health, launch, project_root, read_endpoint


def main() -> int:
    launch(open_browser=False)
    endpoint = read_endpoint(project_root())
    if endpoint is None or not health(endpoint):
        raise SystemExit("El centro de control no está disponible.")
    origin = f"http://{HOST}:{endpoint['port']}"
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    with opener.open(f"{origin}/?token={endpoint['token']}", timeout=5) as response:
        page = response.read().decode("utf-8")
    match = re.search(r'^const csrf = "([^"]+)";', page, flags=re.MULTILINE)
    if match is None:
        raise SystemExit("No se encontró el token CSRF en la interfaz autenticada.")
    csrf = match.group(1)
    headers = {
        "Origin": origin,
        "X-CSRF-Token": csrf,
        "Content-Type": "application/json",
    }

    def get_tools() -> list[dict[str, object]]:
        with opener.open(f"{origin}/api/tools", timeout=5) as response:
            return json.load(response)["tools"]

    def post(tool_id: str, action: str, *, confirmed: bool = False) -> dict[str, object]:
        request = urllib.request.Request(
            f"{origin}/api/tools/{tool_id}/{action}",
            method="POST",
            data=json.dumps({"confirmed": confirmed}).encode("utf-8"),
            headers=headers,
        )
        with opener.open(request, timeout=15) as response:
            return json.load(response)["result"]

    tools = get_tools()
    if len(tools) != 9:
        raise SystemExit(f"Se esperaban 9 herramientas y se recibieron {len(tools)}.")
    opened = post("open_project", "start")
    diagnostic = post("diagnostics", "start")
    running = {item["id"]: item["status"] for item in get_tools()}
    if running.get("diagnostics") != "running":
        raise SystemExit("Diagnóstico no apareció en ejecución después del inicio HTTP.")
    stopped = post("diagnostics", "stop")
    report = {
        "endpoint": origin,
        "bind": endpoint.get("bind"),
        "tool_count": len(tools),
        "open_project": opened["outcome"],
        "diagnostics_start": diagnostic["outcome"],
        "diagnostics_stop": stopped["outcome"],
        "voice_status": running.get("voice"),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
