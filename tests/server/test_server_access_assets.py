from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _settings(path: str) -> dict:
    return json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))


def test_local_and_public_settings_declare_available_access_assets() -> None:
    for settings_path in ("deploy/local.settings.json", "deploy/remote.settings.json"):
        settings = _settings(settings_path)
        methods = settings["management_access"]["methods"]
        assert methods
        for method in methods:
            script = method["script"]
            asset = REPO_ROOT / "server" / "access-scripts" / script["id"]
            body = asset.read_bytes()
            assert asset.is_file()
            assert os.access(asset, os.X_OK)
            assert hashlib.sha256(body).hexdigest() == script["sha256"]
            assert "command" not in json.dumps(method).lower()
            assert "password" not in json.dumps(method).lower()
            assert "private_key" not in json.dumps(method).lower()
