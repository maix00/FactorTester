from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.client import FactorTesterClient
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.local_profile import validate_local_profile
from tools.cli.release.adapters.profile_binding import adapter_binding


def test_local_profile_is_strict_private_and_version_independent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = LocalProfileStore(root)
    profile = new_local_profile(
        profile_id="research-a",
        display_name="Research A",
        server_url="http://127.0.0.1:8123/",
        workspace_root=tmp_path / "workspace",
    )
    stored = store.save(profile)

    assert stored["server"]["base_url"] == "http://127.0.0.1:8123"
    assert store.load("research-a") == stored
    path = root / "profiles" / "research-a.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert not (root / "current.json").exists()
    assert not {"password", "token", "email"}.intersection(stored)

    with pytest.raises(ValueError, match="fields"):
        validate_local_profile({**stored, "token": "must-not-be-stored"})


def test_client_cli_exposes_generic_profile_and_adapter_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "client-support"
    monkeypatch.setenv("FACTORTESTER_CLIENT_ROOT", str(root))
    runner = CliRunner()

    result = runner.invoke(cli, [
        "client", "profile", "init",
        "--profile-id", "research-a",
        "--display-name", "Research A",
        "--server-url", "http://127.0.0.1:8123",
        "--workspace-root", str(tmp_path / "workspace"),
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["profile_id"] == "research-a"
    assert runner.invoke(cli, ["client", "profile", "list"]).exit_code == 0
    adapters = runner.invoke(cli, ["client", "adapter", "list"])
    assert adapters.exit_code == 0
    assert json.loads(adapters.output) == []


def test_local_agent_identity_resumes_without_provider_or_model_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "client-support"
    monkeypatch.setenv("FACTORTESTER_CLIENT_ROOT", str(root))
    store = LocalProfileStore(root)
    store.save(new_local_profile(
        profile_id="agent-profile",
        display_name="Research Agent",
        server_url="http://127.0.0.1:8123",
        workspace_root=tmp_path / "workspace",
    ))
    runner = CliRunner()
    configured = runner.invoke(cli, [
        "client", "profile", "agent", "set", "agent-profile",
        "--agent-id", "planner-a",
        "--role", "planning",
        "--workspace-id", "workspace-1",
    ])
    assert configured.exit_code == 0, configured.output
    seen: list[tuple[str, dict]] = []

    def fake_resume(self, agent_id: str, **kwargs):
        seen.append((agent_id, kwargs))
        return {
            "schema_version": 1,
            "agent": {"agent_id": agent_id, "role": kwargs["role"]},
            "resume_ref": "sha256:stable",
            "packet_bytes": 180,
        }

    monkeypatch.setattr(FactorTesterClient, "resume_agent", fake_resume)
    first = runner.invoke(cli, [
        "agent-flow", "resume-local", "agent-profile", "planner-a",
    ])
    second = runner.invoke(cli, [
        "agent-flow", "resume-local", "agent-profile", "planner-a",
    ])

    assert first.exit_code == second.exit_code == 0
    assert json.loads(first.output) == json.loads(second.output)
    assert seen == [
        ("planner-a", {
            "role": "planning",
            "workspace_id": "workspace-1",
            "instance_id": "",
            "branch_id": "",
        }),
    ] * 2
    profile = store.load("agent-profile")
    serialized = json.dumps(profile).lower()
    assert "runtime_id" not in serialized
    assert "model_id" not in serialized
    assert "codex" not in serialized


def test_adapter_credentials_are_opaque_keychain_references(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = LocalProfileStore(root)
    store.save(new_local_profile(
        profile_id="human",
        display_name="Human",
        server_url="http://127.0.0.1:8123",
        workspace_root=tmp_path / "workspace",
    ))

    stored = store.upsert_adapter("human", {
        "adapter_id": "ai-trader",
        "enabled": True,
        "credential_ref": "keychain://ai4trade/token",
        "configuration_ref": "profile://ai-trader",
    })
    assert stored["adapters"][0]["credential_ref"].startswith("keychain://")
    with pytest.raises(ValueError, match="opaque"):
        store.upsert_adapter("human", {
            "adapter_id": "ai-trader",
            "enabled": True,
            "credential_ref": "secret-token",
            "configuration_ref": "",
        })


def test_adapter_profile_binding_exposes_only_opaque_references(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    config = tmp_path / "vibe.json"
    config.write_text('{"executable": "/tmp/vibe-trading"}')
    store = LocalProfileStore(root)
    store.save(new_local_profile(
        profile_id="human",
        display_name="Human",
        server_url="http://127.0.0.1:8123",
        workspace_root=tmp_path / "workspace",
    ))
    store.upsert_adapter("human", {
        "adapter_id": "vibe-trading",
        "enabled": True,
        "credential_ref": "keychain://com.gtht.client.adapters/human/vibe",
        "configuration_ref": config.as_uri(),
    })

    binding = adapter_binding(root, "human", "vibe-trading")

    assert binding["FACTORTESTER_ADAPTER_PROFILE_ID"] == "human"
    assert binding["FACTORTESTER_ADAPTER_CONFIGURATION_REF"] == str(config)
    assert binding["FACTORTESTER_ADAPTER_CREDENTIAL_REF"].startswith(
        "keychain://"
    )
    assert "password" not in json.dumps(binding).lower()
