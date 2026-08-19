from __future__ import annotations

import json
from pathlib import Path

from tools.cli.agent_auth import AgentCapability, load_capability
from tools.cli.core.context import client_from_config
from tools.cli.http import HttpSession


def _write_capability(path: Path, *, base_url: str = "http://127.0.0.1:7998") -> None:
    path.write_text(
        json.dumps({
            "schema_version": 1,
            "kind": "profile-agent",
            "base_url": base_url,
            "token": "agent-session-token",
            "profile_id": "profile-main",
            "claim_id": "claim-1",
        }),
        encoding="utf-8",
    )


def test_profile_agent_capability_adds_scoped_headers(tmp_path: Path) -> None:
    capability = AgentCapability(
        base_url="http://127.0.0.1:7998",
        token="agent-session-token",
        profile_id="profile-main",
        claim_id="claim-1",
    )
    session = HttpSession(
        capability.base_url,
        cookies=tmp_path / "cookies.lwp",
        agent_capability=capability,
        bearer_token=capability.token,
    )

    headers = session._headers({"Accept": "application/json"})

    assert headers["Authorization"] == "Bearer agent-session-token"
    assert headers["X-FactorTester-Agent"] == "profile"
    assert headers["X-FactorTester-Agent-Profile"] == "profile-main"
    assert headers["X-FactorTester-Agent-Claim"] == "claim-1"


def test_profile_agent_cli_uses_capability_without_user_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    capability_path = tmp_path / "factor-tester-agent.json"
    _write_capability(capability_path)
    monkeypatch.setenv("FACTORTESTER_AGENT_CAPABILITY_FILE", str(capability_path))
    monkeypatch.setenv("FACTORTESTER_CONFIG", str(tmp_path / "missing.json"))
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))

    client = client_from_config()

    assert client.session.base_url == "http://127.0.0.1:7998"
    assert client.session.bearer_token == "agent-session-token"
    assert client.session.agent_capability is not None
    assert load_capability(capability_path).profile_id == "profile-main"
