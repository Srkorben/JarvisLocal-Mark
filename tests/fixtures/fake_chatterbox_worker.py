from __future__ import annotations

import base64
import json
import struct
import sys
import time


def reply(value: dict) -> None:
    print(json.dumps(value, separators=(",", ":")), flush=True)


reply({"type": "ready", "sample_rate": 24000, "device": "cpu"})
for line in sys.stdin:
    request = json.loads(line)
    if request.get("command") == "close":
        reply({"id": request.get("id"), "ok": True})
        break
    if request.get("text") == "slow":
        time.sleep(10)
    pcm = struct.pack("<hhhh", 10, -10, 20, -20)
    reply(
        {
            "id": request.get("id"),
            "ok": True,
            "sample_rate": 24000,
            "channels": 1,
            "pcm16_base64": base64.b64encode(pcm).decode("ascii"),
        }
    )
