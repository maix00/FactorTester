from pathlib import Path

import pytest

from tools.cli.agent_auth import AgentCapability
from tools.cli.http import HttpClientError
from tools.cli.release.research_reporting.public_research import notify


@pytest.mark.parametrize("unavailable", [False, True])
def test_agent_report_notification_uses_injected_endpoint_and_keeps_local_commit(
    monkeypatch, unavailable,
):
    capability = AgentCapability("http://127.0.0.1:17998", "test-token", "self", "claim")
    monkeypatch.setattr("tools.cli.agent_auth.load_capability", lambda: capability)
    monkeypatch.setattr(notify, "_load_snapshot", lambda paths: {})
    monkeypatch.setattr(notify, "build_upload_projection", lambda snapshot: {
        "report_id": "report:v1:test", "generation": 4,
    })
    calls = []

    class Session:
        def __init__(self, endpoint, **kwargs):
            assert endpoint == capability.base_url
            assert kwargs["agent_capability"] is capability
            assert kwargs["persist_cookies"] is False

        def post(self, route, payload):
            calls.append((route, payload))
            if unavailable:
                raise HttpClientError(503, route, "temporarily unavailable")

    monkeypatch.setattr("tools.cli.http.HttpSession", Session)
    # Server workspaces intentionally have no users/<account> path segment.
    notify.sync_manager({"root": Path("/workspace/packages/report/main/research")})
    assert len(calls) == 1
    route, payload = calls[0]
    assert route == "/api/research-publications/sync"
    assert "owner_ref" not in payload  # Manager derives it from authentication.
    assert payload["branch_ref"] == "main"
    assert payload["projection"]["generation"] == 4
