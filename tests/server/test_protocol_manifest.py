from __future__ import annotations

from flask import Flask

from server.modules.shared import shared_bp
from server.modules.shared import protocol_manifest as routes
from server.services.protocol_manifest import protocol_manifest


def _app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(shared_bp)
    return app


def test_protocol_manifest_is_compact_deterministic_and_authenticated() -> None:
    client = _app().test_client()

    response = client.get(
        "/api/protocol-manifest",
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 401

    with client.session_transaction() as session:
        session["username"] = "alice"

    first = client.get("/api/protocol-manifest").get_json()
    second = client.get("/api/protocol-manifest").get_json()

    assert first == second
    assert first == {"success": True, **protocol_manifest()}
    assert first["protocol"] == {
        "name": "factortester-remote-research",
        "current": 1,
        "minimum_client": 1,
    }
    assert first["capabilities"]
    assert all(set(item) == {"id", "version"} for item in first["capabilities"])
    assert len(str(first)) < 2_000
    assert len(first["manifest_hash"]) == 64
    assert "/Users/" not in str(first)
