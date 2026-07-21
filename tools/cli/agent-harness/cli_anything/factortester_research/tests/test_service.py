from __future__ import annotations

import json
from urllib.parse import parse_qs

from cli_anything.factortester_research.core import service


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_service_client_uses_bearer_and_opaque_instance_id(monkeypatch) -> None:
    requests = []

    def open_request(request, timeout):
        requests.append(request)
        if request.method == "GET":
            return _Response({
                "worktrees": [{
                    "instance_id": "worktree-opaque",
                    "label": "fix/issue-141",
                    "branch": "fix/issue-141",
                    "port": 8141,
                    "running": True,
                    "port_in_use": True,
                }],
            })
        return _Response({
            "success": True,
            "instance_id": "worktree-opaque",
            "message": "restarted",
        })

    monkeypatch.setattr(service, "urlopen", open_request)

    rows = service.fetch_worktrees(capability_token="secret")
    result = service.post_manager_action(
        "restart-bundle", admin_port=7998,
        instance_id=rows[0].instance_id, capability_token="secret",
    )

    assert rows[0].instance_id == "worktree-opaque"
    assert not hasattr(rows[0], "path")
    assert requests[0].get_header("Authorization") == "Bearer secret"
    assert requests[1].get_header("Authorization") == "Bearer secret"
    assert parse_qs(requests[1].data.decode("utf-8")) == {
        "instance_id": ["worktree-opaque"],
    }
    assert result["success"] is True
