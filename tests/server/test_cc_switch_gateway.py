from __future__ import annotations

import json
from pathlib import Path

import pytest

import server.manager.services.cc_switch_gateway as gateway_module
from server.manager.services.agent_app_server_errors import AgentAppServerError
from server.manager.services.cc_switch_gateway import CCSwitchGateway


def _provider(protocol: str = "anthropic_messages") -> dict[str, str]:
    return {
        "provider_id": "provider-1",
        "label": "Private provider",
        "protocol": protocol,
        "base_url": "https://api.example.test/v1",
        "default_model": "research-model",
        "secret": "super-secret-token",
    }


def test_cc_switch_gateway_uses_profile_private_state_and_loopback(tmp_path: Path) -> None:
    gateway = CCSwitchGateway(
        profile_state_root=tmp_path / "profile-a",
        provider=_provider(),
        binary="cc-switch",
    )

    plan = gateway.plan(port=17321)

    assert plan.environment["CC_SWITCH_CONFIG_DIR"].startswith(
        str(tmp_path / "profile-a")
    )
    session_root = Path(plan.environment["CC_SWITCH_CONFIG_DIR"]).parent
    assert plan.environment["HOME"] == str(session_root / "home")
    assert plan.environment["CODEX_HOME"] == str(session_root / "codex")
    assert plan.environment["XDG_CONFIG_HOME"] == str(session_root / "xdg-config")
    assert plan.environment["XDG_STATE_HOME"] == str(session_root / "xdg-state")
    assert plan.proxy_url == "http://127.0.0.1:17321/v1"
    assert "--listen-address" in plan.serve_command
    assert plan.serve_command[
        plan.serve_command.index("--listen-address") + 1
    ] == "127.0.0.1"
    assert "--takeover" not in plan.serve_command
    assert "super-secret-token" not in " ".join(
        [*plan.setup_command, *plan.switch_command, *plan.config_command, *plan.serve_command]
    )

    settings = json.loads(plan.provider_config_path.read_text(encoding="utf-8"))
    assert settings["auth"]["OPENAI_API_KEY"] == "super-secret-token"
    assert plan.provider_config_path.stat().st_mode & 0o077 == 0


def test_cc_switch_gateway_maps_supported_codex_protocols(tmp_path: Path) -> None:
    expected = {
        "openai_responses": "responses",
        "openai_chat": "chat",
        "anthropic_messages": "anthropic",
    }

    for protocol, api_format in expected.items():
        gateway = CCSwitchGateway(
            profile_state_root=tmp_path / protocol,
            provider=_provider(protocol),
        )
        plan = gateway.plan(port=17322)

        assert plan.setup_command[
            plan.setup_command.index("--api-format") + 1
        ] == api_format


def test_cc_switch_gateway_classifies_incompatible_protocol(tmp_path: Path) -> None:
    gateway = CCSwitchGateway(
        profile_state_root=tmp_path / "profile-a",
        provider=_provider("gemini_native"),
    )

    with pytest.raises(AgentAppServerError) as error:
        gateway.plan(port=17322)

    assert error.value.code == "protocol_incompatible"


def test_cc_switch_gateway_classifies_missing_runtime(tmp_path: Path, monkeypatch) -> None:
    gateway = CCSwitchGateway(
        profile_state_root=tmp_path / "profile-a",
        provider=_provider(),
    )
    monkeypatch.setattr(gateway_module.shutil, "which", lambda _binary: None)

    with pytest.raises(AgentAppServerError) as error:
        gateway.start()

    assert error.value.code == "runtime_missing"


def test_cc_switch_gateway_child_provider_uses_local_credential(tmp_path: Path) -> None:
    gateway = CCSwitchGateway(
        profile_state_root=tmp_path / "profile-a",
        provider=_provider(),
    )
    plan = gateway.plan(port=17323)

    child = plan.child_provider

    assert child["base_url"] == "http://127.0.0.1:17323/v1"
    assert child["protocol"] == "openai_responses"
    assert child["secret"] != "super-secret-token"
    assert str(child["secret"])


def test_cc_switch_gateway_routes_upstream_through_manager_proxy(tmp_path: Path) -> None:
    gateway = CCSwitchGateway(
        profile_state_root=tmp_path / "profile-a",
        provider=_provider(),
        proxy_url="http://127.0.0.1:7890",
    )

    plan = gateway.plan(port=17324)

    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        assert plan.environment[key] == "http://127.0.0.1:7890"
    assert "127.0.0.1" in plan.environment["NO_PROXY"]
    assert "localhost" in plan.environment["NO_PROXY"]


def test_cc_switch_gateway_does_not_inherit_manager_secrets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_CONTROL_DB_PASSWORD", "database-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "manager-openai-secret")
    monkeypatch.setenv("UNRELATED_DEPLOY_TOKEN", "deployment-secret")
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")
    gateway = CCSwitchGateway(
        profile_state_root=tmp_path / "profile-a",
        provider=_provider(),
    )

    plan = gateway.plan(port=17325)

    assert plan.environment["PATH"] == "/usr/local/bin:/usr/bin"
    assert "FACTORTESTER_CONTROL_DB_PASSWORD" not in plan.environment
    assert "OPENAI_API_KEY" not in plan.environment
    assert "UNRELATED_DEPLOY_TOKEN" not in plan.environment


def test_two_profile_gateways_never_share_state_ports_or_credentials(
    tmp_path: Path,
) -> None:
    provider_a = _provider("openai_chat")
    provider_a.update({
        "provider_id": "provider-a",
        "secret": "secret-a",
        "default_model": "model-a",
    })
    provider_b = _provider("anthropic_messages")
    provider_b.update({
        "provider_id": "provider-b",
        "secret": "secret-b",
        "default_model": "model-b",
    })

    plan_a = CCSwitchGateway(
        profile_state_root=tmp_path / "profile-a",
        provider=provider_a,
    ).plan(port=17331)
    plan_b = CCSwitchGateway(
        profile_state_root=tmp_path / "profile-b",
        provider=provider_b,
    ).plan(port=17332)

    assert plan_a.environment["CC_SWITCH_CONFIG_DIR"] != plan_b.environment[
        "CC_SWITCH_CONFIG_DIR"
    ]
    assert plan_a.proxy_url != plan_b.proxy_url
    assert plan_a.child_provider["secret"] != plan_b.child_provider["secret"]
    assert plan_a.child_provider["default_model"] == "model-a"
    assert plan_b.child_provider["default_model"] == "model-b"
    config_a = plan_a.provider_config_path.read_text(encoding="utf-8")
    config_b = plan_b.provider_config_path.read_text(encoding="utf-8")
    assert "secret-a" in config_a and "secret-b" not in config_a
    assert "secret-b" in config_b and "secret-a" not in config_b
