from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.agent_auth import AgentCapability
from tools.cli.app import cli
from tools.cli.commands import server_profile_agent


class _FakeClient:
    def __init__(self) -> None:
        self.settings: dict[str, object] = {}

    def profile_agent_status(self, profile_id: str):
        return {"profile_id": profile_id, "status": {"running": True}}

    def list_profile_agent_models(self, profile_id: str, *, refresh: bool = False):
        return {
            "profile_id": profile_id,
            "models": [{"id": "research-model"}],
            "refresh": refresh,
        }

    def list_profile_agent_conversations(self, profile_id: str):
        return {
            "profile_id": profile_id,
            "conversations": [{"conversation_id": "conversation-1"}],
        }

    def update_profile_agent_conversation_settings(
        self,
        profile_id: str,
        conversation_id: str,
        *,
        model_id: str,
        reasoning_effort: str,
        service_tier: str,
    ):
        self.settings = {
            "profile_id": profile_id,
            "conversation_id": conversation_id,
            "model_id": model_id,
            "reasoning_effort": reasoning_effort,
            "service_tier": service_tier,
        }
        return {"conversation": dict(self.settings)}

    def start_profile_agent(self, profile_id: str):
        return {"profile_id": profile_id, "status": {"running": True}}

    def stop_profile_agent(self, profile_id: str):
        return {"profile_id": profile_id, "stopped": True}


def test_server_profile_agent_commands_use_explicit_profile(monkeypatch) -> None:
    client = _FakeClient()
    monkeypatch.setattr(server_profile_agent, "client_from_config", lambda: client)
    monkeypatch.setattr(server_profile_agent, "load_capability", lambda: None)
    runner = CliRunner()

    models = runner.invoke(cli, [
        "agents", "profile", "--profile-id", "maxc", "models", "--refresh",
        "--json",
    ])
    settings = runner.invoke(cli, [
        "agents", "profile", "--profile-id", "maxc", "conversation", "settings",
        "conversation-1", "--model", "research-model", "--effort", "high",
        "--service-tier", "fast", "--json",
    ])

    assert models.exit_code == 0, models.output
    assert json.loads(models.output)["models"][0]["id"] == "research-model"
    assert settings.exit_code == 0, settings.output
    assert client.settings == {
        "profile_id": "maxc",
        "conversation_id": "conversation-1",
        "model_id": "research-model",
        "reasoning_effort": "high",
        "service_tier": "fast",
    }


def test_server_profile_agent_capability_is_locked_to_issued_profile(
    monkeypatch,
) -> None:
    client = _FakeClient()
    capability = AgentCapability(
        base_url="http://127.0.0.1:7998",
        token="secret",
        profile_id="maxc",
        claim_id="claim-1",
    )
    monkeypatch.setattr(server_profile_agent, "client_from_config", lambda: client)
    monkeypatch.setattr(
        server_profile_agent, "load_capability", lambda: capability,
    )
    runner = CliRunner()

    implicit = runner.invoke(cli, ["agents", "profile", "status", "--json"])
    rejected = runner.invoke(cli, [
        "agents", "profile", "--profile-id", "maxb", "status", "--json",
    ])

    assert implicit.exit_code == 0, implicit.output
    assert json.loads(implicit.output)["profile_id"] == "maxc"
    assert rejected.exit_code != 0
    assert "signed for another Profile" in rejected.output


def test_server_profile_agent_requires_profile_outside_agent_runtime(
    monkeypatch,
) -> None:
    monkeypatch.setattr(server_profile_agent, "load_capability", lambda: None)

    result = CliRunner().invoke(cli, ["agents", "profile", "status"])

    assert result.exit_code != 0
    assert "--profile-id is required" in result.output
