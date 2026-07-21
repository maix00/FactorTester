from __future__ import annotations

import json

import pytest

from server.services import manager_control


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


def test_manager_snapshot_uses_loopback_bearer_and_projects_safe_fields(
    monkeypatch,
) -> None:
    observed = []
    monkeypatch.setenv("GTHT_MANAGER_CAPABILITY_TOKEN", "secret-token")
    monkeypatch.setattr(
        manager_control,
        "urlopen",
        lambda request, timeout: observed.append((request, timeout)) or _Response({
            "worktrees": [{
                "instance_id": "worktree-opaque",
                "label": "issue-141",
                "branch": "fix/issue-141",
                "port": 8141,
                "running": True,
                "daemon_running": True,
                "port_in_use": True,
                "path": "/Users/private/source",
            }],
            "vibe_trading": {
                "instance_id": "service-vibe-trading",
                "port": 7899,
                "running": False,
                "port_in_use": True,
            },
        }),
    )

    value = manager_control.manager_snapshot()

    request, timeout = observed[0]
    assert request.full_url == "http://127.0.0.1:7998/api/worktrees"
    assert request.get_header("Authorization") == "Bearer secret-token"
    assert timeout == 3.0
    assert [item["kind"] for item in value["instances"]] == [
        "factortester",
        "external_service",
    ]
    assert value["instances"][0]["status"] == "running"
    assert value["instances"][0]["allowed_actions"] == ["stop", "restart"]
    assert value["instances"][1]["status"] == "occupied"
    assert value["instances"][1]["allowed_actions"] == []
    assert "/Users/" not in json.dumps(value)


def test_manager_action_resolves_opaque_identity_then_posts_fixed_route(
    monkeypatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        manager_control,
        "manager_snapshot",
        lambda **_: {"instances": [{
            "instance_id": "worktree-opaque",
            "kind": "factortester",
            "allowed_actions": ["stop", "restart"],
        }]},
    )
    monkeypatch.setattr(
        manager_control,
        "_request",
        lambda path, **kwargs: calls.append((path, kwargs))
        or {"success": True},
    )

    value = manager_control.manager_action("worktree-opaque", "restart")

    assert value == {
        "instance_id": "worktree-opaque",
        "action": "restart",
        "submitted": True,
    }
    assert calls == [(
        "/restart-bundle",
        {
            "timeout": 180.0,
            "form": {"instance_id": "worktree-opaque"},
            "respond_async": True,
        },
    )]


def test_manager_action_rejects_an_action_not_allowed_by_current_state(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        manager_control,
        "manager_snapshot",
        lambda **_: {"instances": [{
            "instance_id": "worktree-opaque",
            "kind": "factortester",
            "allowed_actions": ["start"],
        }]},
    )

    with pytest.raises(ValueError, match="not allowed"):
        manager_control.manager_action("worktree-opaque", "restart")


@pytest.mark.parametrize(
    ("api", "daemon", "port", "status", "actions"),
    [
        (True, True, True, "running", ["stop", "restart"]),
        (True, False, True, "degraded", ["stop", "restart"]),
        (False, True, False, "degraded", ["stop", "restart"]),
        (False, False, True, "occupied", []),
        (False, False, False, "stopped", ["start"]),
    ],
)
def test_worktree_status_keeps_api_and_daemon_semantics(
    api,
    daemon,
    port,
    status,
    actions,
) -> None:
    value = manager_control._worktree_summary({
        "instance_id": "worktree-opaque",
        "running": api,
        "daemon_running": daemon,
        "port_in_use": port,
    })

    assert value["status"] == status
    assert value["allowed_actions"] == actions
