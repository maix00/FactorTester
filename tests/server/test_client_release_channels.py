from __future__ import annotations

import json
from pathlib import Path

from flask import Flask

from script.release.update_manifest import (
    create_update_manifest,
    write_update_manifest,
)
from server.modules.shared import shared_bp
from server.modules.shared import client_releases as routes
from tests.release.test_update_channel_manifest import _keys


def test_public_release_channel_is_static_cacheable_and_conditional(
    tmp_path: Path,
    monkeypatch,
) -> None:
    private, public = _keys(tmp_path / "keys")
    dmg = tmp_path / "FactorTester-Client.dmg"
    dmg.write_bytes(b"installer")
    manifest = create_update_manifest(
        version="2.0.0",
        build=7,
        channel="stable",
        dmg=dmg,
        dmg_url="https://github.example/FactorTester-Client.dmg",
        minimum_client="1.2.0",
        mandatory=True,
        published_at="2026-07-20T12:00:00Z",
        private_key=private,
        public_key=public,
    )
    root = tmp_path / "channels"
    write_update_manifest(root / "stable.json", manifest)
    monkeypatch.setattr(routes, "release_manifest_root", lambda: root)
    monkeypatch.setattr(routes, "trusted_release_public_key", lambda: public)
    app = Flask(__name__)
    app.register_blueprint(shared_bp)
    client = app.test_client()

    response = client.get("/api/client/releases/stable.json")
    assert response.status_code == 200
    assert response.get_json() == manifest
    assert response.headers["Cache-Control"] == (
        "public, max-age=300, stale-if-error=86400"
    )
    assert response.headers["ETag"]

    cached = client.get(
        "/api/client/releases/stable.json",
        headers={"If-None-Match": response.headers["ETag"]},
    )
    assert cached.status_code == 304
    assert cached.data == b""
    assert cached.headers["ETag"] == response.headers["ETag"]


def test_server_refuses_unsigned_or_unknown_channel(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _, public = _keys(tmp_path / "keys")
    root = tmp_path / "channels"
    root.mkdir()
    (root / "stable.json").write_text(json.dumps({
        "schema_version": 1,
        "channel": "stable",
    }))
    monkeypatch.setattr(routes, "release_manifest_root", lambda: root)
    monkeypatch.setattr(routes, "trusted_release_public_key", lambda: public)
    app = Flask(__name__)
    app.register_blueprint(shared_bp)
    client = app.test_client()

    assert client.get("/api/client/releases/stable.json").status_code == 503
    assert client.get("/api/client/releases/nightly.json").status_code == 503
