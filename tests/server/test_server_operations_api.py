from __future__ import annotations

import json
from pathlib import Path

from flask import Flask
import pytest

from server.server_operations import server_operations_bp


ROOT = Path(__file__).resolve().parents[2]


def _client(monkeypatch, *, role: str):
    monkeypatch.setattr(
        "server.server_operations.get_account",
        lambda username: {
            "username": username,
            "role": role,
            "is_admin": role == "super_admin",
        },
    )
    app = Flask(
        __name__,
        template_folder=None,
        static_folder=None,
    )
    app.secret_key = "test"
    app.register_blueprint(server_operations_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "root"
    return client


def test_shared_module_manifest_limits_server_operations_to_super_admin() -> None:
    manifest = json.loads(
        (ROOT / "static/config/modules.json").read_text(encoding="utf-8")
    )

    module = next(
        item for item in manifest["modules"]
        if item["id"] == "server_operations"
    )
    assert module["path"] == "/manager?section=server"
    assert module["roles"] == ["super_admin"]


def test_shared_module_manifest_restores_home_and_excludes_test_launchers() -> None:
    manifest = json.loads(
        (ROOT / "static/config/modules.json").read_text(encoding="utf-8")
    )
    module_ids = [item["id"] for item in manifest["modules"]]

    assert module_ids[0] == "home"
    assert "ic-test" not in module_ids
    assert "backtest" not in module_ids


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("get", "/admin/api/server-instances", None),
        (
            "post",
            "/admin/api/server-instances/worktree-opaque/actions",
            {"action": "restart"},
        ),
    ],
)
def test_non_super_admin_cannot_use_server_operations_api(
    monkeypatch,
    method: str,
    path: str,
    json_body,
) -> None:
    client = _client(monkeypatch, role="org_admin")

    response = getattr(client, method)(path, json=json_body)

    assert response.status_code == 403
    assert response.get_json()["success"] is False


def test_super_admin_reads_bounded_manager_snapshot_without_capability(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "server.server_operations.manager_snapshot",
        lambda: {
            "instances": [{
                "instance_id": "worktree-opaque",
                "label": "issue-141",
                "branch": "fix/issue-141",
                "port": 8141,
                "running": True,
                "daemon_running": True,
                "port_in_use": True,
                "kind": "factortester",
                "status": "running",
                "allowed_actions": ["stop", "restart"],
            }],
        },
    )
    client = _client(monkeypatch, role="super_admin")

    response = client.get("/admin/api/server-instances")

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "instances": [{
            "instance_id": "worktree-opaque",
            "label": "issue-141",
            "branch": "fix/issue-141",
            "port": 8141,
            "running": True,
            "daemon_running": True,
            "port_in_use": True,
            "kind": "factortester",
            "status": "running",
            "allowed_actions": ["stop", "restart"],
        }],
    }
    serialized = response.get_data(as_text=True)
    assert "capability" not in serialized
    assert "/Users/" not in serialized


def test_super_admin_can_submit_one_predefined_instance_action(
    monkeypatch,
) -> None:
    observed = []
    monkeypatch.setattr(
        "server.server_operations.manager_action",
        lambda instance_id, action: observed.append((instance_id, action))
        or {
            "instance_id": instance_id,
            "action": action,
            "submitted": True,
        },
    )
    client = _client(monkeypatch, role="super_admin")

    response = client.post(
        "/admin/api/server-instances/worktree-opaque/actions",
        json={"action": "restart"},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "instance_id": "worktree-opaque",
        "action": "restart",
        "submitted": True,
    }
    assert observed == [("worktree-opaque", "restart")]


def test_super_admin_can_submit_explicit_force_stop(monkeypatch) -> None:
    observed = []
    monkeypatch.setattr(
        "server.server_operations.manager_action",
        lambda instance_id, action: observed.append((instance_id, action))
        or {
            "instance_id": instance_id,
            "action": action,
            "submitted": True,
        },
    )
    client = _client(monkeypatch, role="super_admin")

    response = client.post(
        "/admin/api/server-instances/worktree-opaque/actions",
        json={"action": "force_stop"},
    )

    assert response.status_code == 200
    assert observed == [("worktree-opaque", "force_stop")]


def test_server_operations_api_rejects_unknown_actions_before_manager_call(
    monkeypatch,
) -> None:
    observed = []
    monkeypatch.setattr(
        "server.server_operations.manager_action",
        lambda instance_id, action: observed.append((instance_id, action)),
    )
    client = _client(monkeypatch, role="super_admin")

    response = client.post(
        "/admin/api/server-instances/worktree-opaque/actions",
        json={"action": "run-arbitrary-command"},
    )

    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert observed == []
