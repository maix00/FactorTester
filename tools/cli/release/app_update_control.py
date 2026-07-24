"""Send update actions to FTClient; Sparkle remains the only updater."""

from __future__ import annotations

import subprocess
from urllib.parse import urlencode


ACTIONS = {"check", "download", "restart"}


def dispatch_app_update(action: str) -> dict:
    if action not in ACTIONS:
        raise ValueError("app update action is invalid")
    url = "factortester://app-update?" + urlencode({"action": action})
    subprocess.run(["open", url], check=True, capture_output=True)
    return {
        "schema_version": 1,
        "action": action,
        "handler": "FTClient/Sparkle",
        "dispatched": True,
    }
