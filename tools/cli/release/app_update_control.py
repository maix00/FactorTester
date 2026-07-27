"""Send update actions to FTClient; Sparkle remains the only updater."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode

from tools.cli.release.locations import default_client_root


ACTIONS = {"check", "download", "restart"}
EXPECTED_STATES = {
    "check": {"available", "current", "failed"},
    "download": {"downloading", "ready", "current", "failed"},
}


def status_path() -> Path:
    return default_client_root() / "app-update-status.json"


def read_status() -> dict:
    path = status_path()
    if not path.is_file():
        return {"schema_version": 1, "state": "unknown"}
    try:
        import json

        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema_version": 1, "state": "unknown"}
    return value if isinstance(value, dict) else {"schema_version": 1, "state": "unknown"}


def dispatch_app_update(action: str, *, wait: float = 0) -> dict:
    if action not in ACTIONS:
        raise ValueError("app update action is invalid")
    before = read_status()
    before_marker = (
        before.get("state"),
        before.get("installed_version"),
        before.get("latest_version"),
        before.get("error"),
        before.get("updated_at"),
    )
    url = "factortester://app-update?" + urlencode({"action": action})
    subprocess.run(["open", url], check=True, capture_output=True)
    result = {
        "schema_version": 1,
        "action": action,
        "handler": "FTClient/Sparkle",
        "dispatched": True,
    }
    if wait > 0 and action in EXPECTED_STATES:
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            status = read_status()
            marker = (
                status.get("state"),
                status.get("installed_version"),
                status.get("latest_version"),
                status.get("error"),
                status.get("updated_at"),
            )
            if (
                marker != before_marker
                and status.get("state") in EXPECTED_STATES[action]
            ):
                result["status"] = status
                return result
            time.sleep(0.25)
        result["status"] = read_status()
        result["timed_out"] = True
    return result
