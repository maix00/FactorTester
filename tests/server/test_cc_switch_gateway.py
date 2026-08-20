from __future__ import annotations

import json
from pathlib import Path

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
    assert plan.proxy_url == "http://127.0.0.1:17321/v1"
    assert "--listen-address" in plan.serve_command
    assert plan.serve_command[
        plan.serve_command.index("--listen-address") + 1
    ] == "127.0.0.1"
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
