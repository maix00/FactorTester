from __future__ import annotations

import io
import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

import server.manager.services.agent_provider_health as provider_health_module
from server.manager.http.agent_app_routes import AgentAppServerRoutesMixin
from server.manager.http.agent_routes import AgentRoutesMixin
from server.manager.services.agent_app_server import AgentAppServerSupervisor
from server.manager.services.agent_app_server_errors import AgentAppServerError
from server.manager.services.agent_conversation_runtime import (
    AgentConversationRuntimeObserver,
)
from server.manager.services.agent_profiles import AgentProfileService
from server.manager.services.agent_provider_health import (
    AgentProviderHealth,
    AgentProviderHealthError,
)
from server.manager.services.agent_workspace import profile_workspace_relative_path
from server.manager.services.cc_switch_gateway import CCSwitchGateway
from server.manager.services.profile_agent_sandbox import ProfileAgentSandbox
from server.manager.storage.agent_provider_store import ProviderStoreError

REPO_ROOT = Path(__file__).resolve().parents[2]
PRINCIPAL = "GTHT@MaxJJW@1234"
PROFILE_ID = "profile-main"


@pytest.fixture(autouse=True)
def _bypass_process_namespace_in_app_server_unit_tests(monkeypatch):
    """Process protocol tests are separate from Bubblewrap boundary tests."""
    monkeypatch.setattr(ProfileAgentSandbox, "command", lambda _self, child: child)


def _fake_codex(path: Path, *, history: bool = False) -> str:
    turns = repr(
        [
            {
                "items": [
                    {
                        "id": "history-user-1",
                        "type": "user_message",
                        "content": [{"type": "input_text", "text": "查询产品"}],
                        "created_at": 2,
                    },
                    {
                        "id": "history-assistant-1",
                        "type": "assistant_message",
                        "text": (
                            "98 个期货品种，2846 个合约路径\n\n"
                            "```bash\n"
                            "factortester product-library list\n"
                            "```"
                        ),
                        "created_at": 3,
                    },
                ],
            }
        ]
        if history
        else []
    )
    path.write_text(
        """#!/usr/bin/env python3
import json
import sys

HISTORY_TURNS = __HISTORY_TURNS__

for raw in sys.stdin:
    request = json.loads(raw)
    method = request.get("method")
    if method == "skills/list":
        result = {"data": [{"cwd": request.get("params", {}).get("cwds", [""])[0], "skills": []}]}
    elif method == "initialize":
        result = {"userAgent": "fake-codex"}
    elif method == "model/list":
        result = {"data": [{
            "id": "research-model-fast",
            "model": "research-model-fast",
            "displayName": "Research Fast",
            "description": "Fast research model",
            "hidden": False,
            "isDefault": False,
            "defaultReasoningEffort": "medium",
            "supportedReasoningEfforts": [
                {"reasoningEffort": "medium", "description": "Balanced"},
                {"reasoningEffort": "high", "description": "Deep"},
            ],
            "defaultServiceTier": None,
            "serviceTiers": [{"id": "fast", "name": "Fast", "description": "Low latency"}],
        }], "nextCursor": None}
    elif method == "thread/start":
        result = {
            "thread": {
                "id": "provider-thread-1",
                "name": "Recovered conversation",
                "createdAt": 1,
                "updatedAt": 1,
                "turns": HISTORY_TURNS,
            },
        }
    elif method in {"thread/resume", "thread/read"}:
        thread_id = request.get("params", {}).get("threadId", "")
        result = {
            "thread": {
                "id": thread_id,
                "name": "Recovered conversation",
                "createdAt": 1,
                "updatedAt": 1,
                "turns": HISTORY_TURNS,
            },
            "resumed": method == "thread/resume",
        }
    elif method == "thread/delete":
        result = {"deleted": True}
    elif method == "turn/steer" and any(
        item.get("text") == "stale turn"
        for item in request.get("params", {}).get("input", [])
    ):
        if "id" in request:
            sys.stdout.write(json.dumps({
                "id": request["id"],
                "error": {"code": -32602, "message": "no active turn"},
            }) + "\\n")
            sys.stdout.flush()
        continue
    else:
        result = {"accepted": method, "params": request.get("params", {})}
        if method == "turn/start":
            result["turn"] = {"id": "turn-active"}
    if "id" in request:
        sys.stdout.write(json.dumps({"id": request["id"], "result": result}) + "\\n")
        sys.stdout.flush()
""".replace("__HISTORY_TURNS__", turns),
        encoding="utf-8",
    )
    os.chmod(path, 0o700)
    return str(path)


def _fake_factor_tester(path: Path) -> str:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    os.chmod(path, 0o700)
    return str(path)


def _provider_health_ok(provider, **_kwargs):
    return {
        "status": "ok",
        "provider_id": provider.get("provider_id", ""),
        "protocol": "openai_compatible",
        "base_url": provider["base_url"],
        "default_model": provider["default_model"],
        "model_available": True,
        "latency_ms": 125,
        "available_models": ["research-model", "research-model-fast"],
        "available_models_truncated": False,
    }


class _ModelResponse:
    status = 200

    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self._payload


def test_openai_provider_health_checks_model_without_returning_secret(monkeypatch):
    clock = iter([100.0, 100.125])
    monkeypatch.setattr(
        provider_health_module.time,
        "monotonic",
        lambda: next(clock),
    )

    def fake_urlopen(request, timeout):
        assert request.full_url == "https://api.openai.com/v1/models"
        assert request.headers["Authorization"] == "Bearer secret-token"
        assert timeout == 10.0
        return _ModelResponse({"data": [{"id": "research-model"}]})

    monkeypatch.setattr(provider_health_module, "urlopen", fake_urlopen)
    result = AgentProviderHealth.test(
        {
            "provider_id": "provider-1",
            "protocol": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "default_model": "research-model",
            "secret": "secret-token",
        }
    )
    assert result["model_available"] is True
    assert result["available_models"] == ["research-model"]
    assert result["available_models_truncated"] is False
    assert result["latency_ms"] == 125
    assert "secret-token" not in json.dumps(result)


def test_openai_provider_health_reports_http_failure_without_secret(monkeypatch):
    def fake_urlopen(request, timeout):
        raise provider_health_module.HTTPError(
            request.full_url,
            401,
            "unauthorized",
            {},
            None,
        )

    monkeypatch.setattr(provider_health_module, "urlopen", fake_urlopen)
    with pytest.raises(AgentProviderHealthError, match="HTTP 401") as error:
        AgentProviderHealth.test(
            {
                "protocol": "openai_compatible",
                "base_url": "https://api.openai.com/v1",
                "default_model": "research-model",
                "secret": "secret-token",
            }
        )
    assert error.value.code == "credential_rejected"
    assert "secret-token" not in str(error.value)


def test_provider_health_classifies_missing_model(monkeypatch):
    monkeypatch.setattr(
        provider_health_module,
        "urlopen",
        lambda _request, timeout: _ModelResponse({"data": [{"id": "other-model"}]}),
    )

    with pytest.raises(AgentProviderHealthError) as error:
        AgentProviderHealth.test(
            {
                "protocol": "openai_responses",
                "base_url": "https://api.openai.com/v1",
                "default_model": "research-model",
                "secret": "secret-token",
            }
        )

    assert error.value.code == "model_unavailable"


@pytest.mark.parametrize(
    ("protocol", "base_url", "expected_url", "header", "payload", "model"),
    [
        (
            "anthropic_messages",
            "https://api.anthropic.com/v1",
            "https://api.anthropic.com/v1/models",
            "X-api-key",
            {"data": [{"id": "claude-research"}]},
            "claude-research",
        ),
        (
            "gemini_native",
            "https://generativelanguage.googleapis.com/v1beta",
            "https://generativelanguage.googleapis.com/v1beta/models",
            "X-goog-api-key",
            {"models": [{"name": "models/gemini-research"}]},
            "gemini-research",
        ),
    ],
)
def test_native_provider_health_uses_protocol_auth_and_model_catalog(
    monkeypatch,
    protocol,
    base_url,
    expected_url,
    header,
    payload,
    model,
):
    def fake_urlopen(request, timeout):
        assert request.full_url == expected_url
        assert request.headers[header] == "secret-token"
        assert "Authorization" not in request.headers
        return _ModelResponse(payload)

    monkeypatch.setattr(provider_health_module, "urlopen", fake_urlopen)

    result = AgentProviderHealth.test(
        {
            "protocol": protocol,
            "base_url": base_url,
            "default_model": model,
            "secret": "secret-token",
        }
    )

    assert result["model_available"] is True
    assert result["protocol"] == protocol


def test_provider_test_uses_manager_mihomo_proxy(tmp_path, monkeypatch):
    observed = {}

    def fake_test(provider, *, proxy_url=""):
        observed["proxy_url"] = proxy_url
        return {
            "status": "ok",
            "provider_id": provider.get("provider_id", ""),
            "protocol": provider["protocol"],
            "base_url": provider["base_url"],
            "default_model": provider["default_model"],
            "model_available": True,
        }

    monkeypatch.setattr(AgentProviderHealth, "test", fake_test)
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
        skill_source_root=REPO_ROOT,
        skill_manifest_path=REPO_ROOT / "server/manager/skills/catalog.json",
        proxy_url_provider=lambda: "http://127.0.0.1:7890",
    )

    result = service.test_provider(
        PRINCIPAL,
        {
            "label": "OpenAI",
            "runtime_kind": "server",
            "protocol": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "default_model": "research-model",
            "network_route": "manager_proxy",
            "token": "secret-token",
        },
    )

    assert result["status"] == "ok"
    assert observed["proxy_url"] == "http://127.0.0.1:7890"


def test_provider_test_does_not_proxy_direct_provider(tmp_path, monkeypatch):
    observed = {}

    def fake_test(provider, *, proxy_url=""):
        observed["proxy_url"] = proxy_url
        return {"status": "ok"}

    monkeypatch.setattr(AgentProviderHealth, "test", fake_test)
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
        skill_source_root=REPO_ROOT,
        skill_manifest_path=REPO_ROOT / "server/manager/skills/catalog.json",
        proxy_url_provider=lambda: "http://127.0.0.1:7890",
    )

    service.test_provider(
        PRINCIPAL,
        {
            "label": "Direct provider",
            "runtime_kind": "server",
            "protocol": "openai_responses",
            "base_url": "https://api.example.test/v1",
            "default_model": "research-model",
            "network_route": "direct",
            "token": "secret-token",
        },
    )

    assert observed["proxy_url"] == ""


def test_provider_test_fails_when_required_manager_proxy_is_unavailable(
    tmp_path,
    monkeypatch,
):
    called = False

    def fake_test(provider, *, proxy_url=""):
        nonlocal called
        called = True
        return {"status": "ok"}

    monkeypatch.setattr(AgentProviderHealth, "test", fake_test)
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
        skill_source_root=REPO_ROOT,
        skill_manifest_path=REPO_ROOT / "server/manager/skills/catalog.json",
        proxy_url_provider=lambda: "",
    )

    with pytest.raises(
        ProviderStoreError, match="Manager network proxy is unavailable"
    ) as error:
        service.test_provider(
            PRINCIPAL,
            {
                "label": "Proxied provider",
                "runtime_kind": "server",
                "protocol": "openai_responses",
                "base_url": "https://api.example.test/v1",
                "default_model": "research-model",
                "network_route": "manager_proxy",
                "token": "secret-token",
            },
        )
    assert error.value.code == "proxy_unavailable"
    assert called is False


def test_unimplemented_codex_protocol_cannot_be_saved(tmp_path):
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
        skill_source_root=REPO_ROOT,
        skill_manifest_path=REPO_ROOT / "server/manager/skills/catalog.json",
    )
    with pytest.raises(ProviderStoreError, match="unsupported"):
        service.save_provider(
            PRINCIPAL,
            {
                "label": "old codex",
                "runtime_kind": "server",
                "protocol": "codex",
                "base_url": "https://api.example.test/v1",
                "default_model": "research-model",
                "token": "secret-token",
            },
        )


def test_server_profile_app_server_starts_and_forwards_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "FACTORTESTER_CLI", _fake_factor_tester(tmp_path / "factortester")
    )
    monkeypatch.setattr(AgentProviderHealth, "test", _provider_health_ok)
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
        skill_source_root=REPO_ROOT,
        skill_manifest_path=REPO_ROOT / "server/manager/skills/catalog.json",
    )
    service.bind_runtime(
        PRINCIPAL,
        PROFILE_ID,
        runtime_kind="server",
        executor_id="public-1",
    )
    provider = service.save_provider(
        PRINCIPAL,
        {
            "label": "fake provider",
            "runtime_kind": "server",
            "protocol": "openai_compatible",
            "base_url": "https://api.example.test/v1",
            "default_model": "research-model",
            "token": "server-secret-token",
        },
    )
    claim = service.claim(
        PRINCIPAL,
        PROFILE_ID,
        provider_id=provider["provider_id"],
        agent_id="agent-a",
    )
    supervisor = AgentAppServerSupervisor(
        service,
        codex_binary=_fake_codex(tmp_path / "fake-codex"),
        heartbeat_interval=0.1,
    )

    status = supervisor.start(PRINCIPAL, PROFILE_ID)
    assert status["ready"] is True
    assert status["running"] is True
    initial_heartbeat = service.runtime_store.active_claim(
        PRINCIPAL,
        PROFILE_ID,
    )["last_heartbeat_at"]
    deadline = time.monotonic() + 1.0
    renewed_heartbeat = initial_heartbeat
    while time.monotonic() < deadline and renewed_heartbeat <= initial_heartbeat:
        time.sleep(0.02)
        renewed = service.runtime_store.active_claim(PRINCIPAL, PROFILE_ID)
        renewed_heartbeat = renewed["last_heartbeat_at"] if renewed else 0
    assert renewed_heartbeat > initial_heartbeat
    conversation = service.create_conversation(PRINCIPAL, PROFILE_ID)
    supervisor.request(
        PRINCIPAL,
        PROFILE_ID,
        "thread/start",
        {},
        conversation_id=conversation["conversation_id"],
    )
    stale_session = supervisor._sessions[(PRINCIPAL, PROFILE_ID)]
    assert stale_session.process is not None
    stale_session.process.stop()
    recovered = supervisor.request(
        PRINCIPAL,
        PROFILE_ID,
        "model/list",
        {"includeHidden": False},
    )
    assert recovered["result"]["data"][0]["id"] == "research-model-fast"
    assert supervisor._sessions[(PRINCIPAL, PROFILE_ID)] is not stale_session
    service.update_conversation_runtime_settings(
        PRINCIPAL,
        PROFILE_ID,
        conversation["conversation_id"],
        model_id="research-model-fast",
        reasoning_effort="high",
        service_tier="fast",
    )
    with pytest.raises(AgentAppServerError, match="conversation catalog"):
        supervisor.request(
            PRINCIPAL,
            PROFILE_ID,
            "thread/list",
            {},
            conversation_id=conversation["conversation_id"],
        )
    response = supervisor.request(
        PRINCIPAL,
        PROFILE_ID,
        "turn/start",
        {
            "prompt": "hello",
            "threadId": "provider-thread-1",
            "skill_ids": [],
        },
        conversation_id=conversation["conversation_id"],
    )
    assert response["result"]["accepted"] == "turn/start"
    assert response["result"]["params"]["model"] == "research-model-fast"
    assert response["result"]["params"]["effort"] == "high"
    assert response["result"]["params"]["serviceTier"] == "fast"
    assert supervisor.status(PRINCIPAL, PROFILE_ID)["processing_turn_id"] == (
        "turn-active"
    )
    assert supervisor.status(PRINCIPAL, PROFILE_ID)["processing_event_after"] >= 0
    steered = supervisor.request(
        PRINCIPAL,
        PROFILE_ID,
        "turn/steer",
        {
            "threadId": "provider-thread-1",
            "turnId": "turn-active",
            "input": [{"type": "text", "text": "steer this turn"}],
        },
        conversation_id=conversation["conversation_id"],
    )
    assert steered["result"]["accepted"] == "turn/steer"
    promoted = supervisor.request(
        PRINCIPAL,
        PROFILE_ID,
        "turn/steer",
        {
            "threadId": "provider-thread-1",
            "turnId": "turn-active",
            "input": [{"type": "text", "text": "stale turn"}],
        },
        conversation_id=conversation["conversation_id"],
    )
    assert promoted["result"]["accepted"] == "turn/start"
    assert promoted["result"]["managerTransition"] == "turn/start"
    with pytest.raises(AgentAppServerError, match="use turn/steer"):
        supervisor.request(
            PRINCIPAL,
            PROFILE_ID,
            "turn/start",
            {"prompt": "must not overlap", "threadId": "provider-thread-1"},
            conversation_id=conversation["conversation_id"],
        )
    config_path = (
        tmp_path
        / "data"
        / profile_workspace_relative_path(PRINCIPAL, PROFILE_ID)
        / ".codex"
        / "config.toml"
    )
    config = config_path.read_text(encoding="utf-8")
    assert "research-model" in config
    assert "server-secret-token" not in config
    assert 'approval_policy = "never"' in config
    assert 'sandbox_mode = "danger-full-access"' in config
    assert "sandbox_workspace_write" not in config
    assert "ignore_default_excludes = false" in config
    assert supervisor.status(PRINCIPAL, PROFILE_ID)["pid"] is not None
    supervisor._observe_runtime_event(
        (PRINCIPAL, PROFILE_ID),
        SimpleNamespace(observe=lambda _payload: None),
        {
            "method": "item/completed",
            "params": {
                "turnId": "turn-active",
                "item": {"id": "final", "type": "agentMessage"},
            },
        },
    )

    with pytest.raises(AgentAppServerError, match="policy override"):
        supervisor.request(
            PRINCIPAL,
            PROFILE_ID,
            "turn/start",
            {
                "prompt": "hello",
                "threadId": "provider-thread-1",
                "approvalPolicy": "never",
            },
            conversation_id=conversation["conversation_id"],
        )
    with pytest.raises(AgentAppServerError, match="only text input"):
        supervisor.request(
            PRINCIPAL,
            PROFILE_ID,
            "turn/start",
            {
                "threadId": "provider-thread-1",
                "input": [{"type": "image", "path": "/etc/passwd"}],
            },
            conversation_id=conversation["conversation_id"],
        )
    with pytest.raises(AgentAppServerError, match="Profile workspace"):
        cwd_conversation = service.create_conversation(PRINCIPAL, PROFILE_ID)
        supervisor.request(
            PRINCIPAL,
            PROFILE_ID,
            "thread/start",
            {"cwd": str(tmp_path)},
            conversation_id=cwd_conversation["conversation_id"],
        )

    supervisor.stop(PRINCIPAL, PROFILE_ID)
    assert supervisor.status(PRINCIPAL, PROFILE_ID)["running"] is False
    assert claim["claim"]["agent_id"] == "agent-a"
    stopped_claim = service.runtime_store.active_claim(PRINCIPAL, PROFILE_ID)
    assert stopped_claim is not None
    assert stopped_claim["status"] == "stopped"

    restarted = supervisor.start(PRINCIPAL, PROFILE_ID)
    assert restarted["ready"] is True
    resumed_claim = service.runtime_store.active_claim(PRINCIPAL, PROFILE_ID)
    assert resumed_claim is not None
    assert resumed_claim["status"] == "claimed"
    supervisor.stop(PRINCIPAL, PROFILE_ID)


def test_two_profile_app_servers_keep_cc_switch_lifecycles_isolated(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        "FACTORTESTER_CLI",
        _fake_factor_tester(tmp_path / "factortester"),
    )
    monkeypatch.setattr(AgentProviderHealth, "test", _provider_health_ok)
    started_roots = []
    started_proxies = []
    stopped_roots = []

    def fake_gateway_start(gateway):
        started_roots.append(gateway.profile_state_root)
        started_proxies.append(gateway.proxy_url)
        return {
            **gateway.provider,
            "protocol": "openai_responses",
            "base_url": f"http://127.0.0.1:{17000 + len(started_roots)}/v1",
            "secret": f"profile-local-token-{len(started_roots)}",
        }

    def fake_gateway_stop(gateway):
        stopped_roots.append(gateway.profile_state_root)

    monkeypatch.setattr(CCSwitchGateway, "start", fake_gateway_start)
    monkeypatch.setattr(CCSwitchGateway, "stop", fake_gateway_stop)
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
        skill_source_root=REPO_ROOT,
        skill_manifest_path=REPO_ROOT / "server/manager/skills/catalog.json",
    )
    profile_ids = ("profile-a", "profile-b")
    protocols = ("openai_chat", "anthropic_messages")
    routes = ("direct", "manager_proxy")
    for profile_id, protocol, network_route in zip(
        profile_ids,
        protocols,
        routes,
        strict=True,
    ):
        service.bind_runtime(
            PRINCIPAL,
            profile_id,
            runtime_kind="server",
            executor_id="public-1",
        )
        provider = service.save_provider(
            PRINCIPAL,
            {
                "label": f"{profile_id} provider",
                "runtime_kind": "server",
                "protocol": protocol,
                "base_url": "https://api.example.test/v1",
                "default_model": f"{profile_id}-model",
                "network_route": network_route,
                "token": f"{profile_id}-upstream-secret",
            },
        )
        service.claim(
            PRINCIPAL,
            profile_id,
            provider_id=provider["provider_id"],
            agent_id=f"{profile_id}-agent",
        )

    supervisor = AgentAppServerSupervisor(
        service,
        codex_binary=_fake_codex(tmp_path / "fake-codex"),
        proxy_url_provider=lambda: "http://127.0.0.1:7890",
    )
    status_a = supervisor.start(PRINCIPAL, profile_ids[0])
    status_b = supervisor.start(PRINCIPAL, profile_ids[1])

    assert status_a["running"] is True
    assert status_b["running"] is True
    assert status_a["pid"] != status_b["pid"]
    assert len(started_roots) == 2
    assert started_roots[0] != started_roots[1]
    assert started_proxies == [
        "",
        "http://127.0.0.1:7890",
    ]

    supervisor.stop(PRINCIPAL, profile_ids[0])

    assert stopped_roots == [started_roots[0]]
    assert supervisor.status(PRINCIPAL, profile_ids[0])["running"] is False
    assert supervisor.status(PRINCIPAL, profile_ids[1])["running"] is True
    supervisor.stop(PRINCIPAL, profile_ids[1])
    assert stopped_roots == started_roots


def test_profile_conversation_survives_agent_stop_and_rebind(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "FACTORTESTER_CLI", _fake_factor_tester(tmp_path / "factortester")
    )
    monkeypatch.setattr(AgentProviderHealth, "test", _provider_health_ok)
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
        skill_source_root=REPO_ROOT,
        skill_manifest_path=REPO_ROOT / "server/manager/skills/catalog.json",
    )
    service.bind_runtime(
        PRINCIPAL,
        PROFILE_ID,
        runtime_kind="server",
        executor_id="public-1",
    )
    provider = service.save_provider(
        PRINCIPAL,
        {
            "label": "fake provider",
            "runtime_kind": "server",
            "protocol": "openai_compatible",
            "base_url": "https://api.example.test/v1",
            "default_model": "research-model",
            "token": "server-secret-token",
        },
    )
    first_claim = service.claim(
        PRINCIPAL,
        PROFILE_ID,
        provider_id=provider["provider_id"],
        agent_id="agent-a",
    )
    supervisor = AgentAppServerSupervisor(
        service,
        codex_binary=_fake_codex(tmp_path / "fake-codex", history=True),
    )
    conversation = service.create_conversation(PRINCIPAL, PROFILE_ID, title="Keep me")

    supervisor.start(PRINCIPAL, PROFILE_ID)
    started = supervisor.request(
        PRINCIPAL,
        PROFILE_ID,
        "thread/start",
        {},
        conversation_id=conversation["conversation_id"],
    )
    assert started["result"]["thread"]["id"] == "provider-thread-1"
    items = supervisor.conversation_items(
        PRINCIPAL,
        PROFILE_ID,
        conversation["conversation_id"],
    )["items"]
    assert [item["type"] for item in items] == ["assistant_message", "user_message"]
    assert items[0]["content"][0]["text"] == (
        "98 个期货品种，2846 个合约路径\n\n```bash\nfactortester product-library list\n```"
    )
    saved = service.conversation(PRINCIPAL, PROFILE_ID, conversation["conversation_id"])
    assert saved["provider_thread_id"] == "provider-thread-1"
    assert saved["provider_id"] == provider["provider_id"]

    refreshed = supervisor.refresh_conversation_history(
        PRINCIPAL,
        PROFILE_ID,
        conversation["conversation_id"],
    )
    assert refreshed is True
    assert (
        len(
            supervisor.conversation_items(
                PRINCIPAL,
                PROFILE_ID,
                conversation["conversation_id"],
            )["items"]
        )
        == 2
    )

    supervisor.stop(PRINCIPAL, PROFILE_ID)
    # A stopped Agent remains readable through a short-lived, read-only
    # Provider app-server.  No SQLite transcript fallback is involved.
    assert (
        len(
            supervisor.conversation_items(
                PRINCIPAL,
                PROFILE_ID,
                conversation["conversation_id"],
            )["items"]
        )
        == 2
    )
    supervisor.thread_reader.close(PRINCIPAL, PROFILE_ID)
    service.release(
        PRINCIPAL,
        first_claim["claim"]["claim_id"],
        agent_id="agent-a",
    )
    # A fresh reader must not depend on an active claim or model-provider
    # network.  Conversation ownership plus the stored Provider binding is
    # sufficient to read this Profile's local thread history.
    assert (
        len(
            supervisor.conversation_items(
                PRINCIPAL,
                PROFILE_ID,
                conversation["conversation_id"],
            )["items"]
        )
        == 2
    )
    supervisor.thread_reader.close(PRINCIPAL, PROFILE_ID)
    second_claim = service.claim(
        PRINCIPAL,
        PROFILE_ID,
        provider_id=provider["provider_id"],
        agent_id="agent-b",
    )

    supervisor.start(PRINCIPAL, PROFILE_ID)
    resumed = supervisor.request(
        PRINCIPAL,
        PROFILE_ID,
        "thread/resume",
        {"threadId": "provider-thread-1"},
        conversation_id=conversation["conversation_id"],
    )
    assert resumed["result"]["resumed"] is True
    assert (
        len(
            supervisor.conversation_items(
                PRINCIPAL,
                PROFILE_ID,
                conversation["conversation_id"],
            )["items"]
        )
        == 2
    )
    supervisor.stop(PRINCIPAL, PROFILE_ID)
    service.release(
        PRINCIPAL,
        second_claim["claim"]["claim_id"],
        agent_id="agent-b",
    )
    service.delete_provider(PRINCIPAL, provider["provider_id"])
    supervisor.thread_reader.close(PRINCIPAL, PROFILE_ID)
    # Local Provider threads stay readable even after their former model
    # connection is removed; thread/read itself performs no model request.
    assert (
        len(
            supervisor.conversation_items(
                PRINCIPAL,
                PROFILE_ID,
                conversation["conversation_id"],
            )["items"]
        )
        == 2
    )
    supervisor.thread_reader.close(PRINCIPAL, PROFILE_ID)


def test_profile_conversation_rejects_a_different_provider_on_resume(tmp_path):
    conversation = {
        "conversation_id": "conversation-1",
        "provider_thread_id": "thread-1",
        "provider_id": "provider-a",
    }
    with pytest.raises(AgentAppServerError, match="another Agent provider"):
        AgentAppServerSupervisor._validate_conversation_request(
            "thread/resume",
            {"threadId": "thread-1"},
            conversation,
            provider_id="provider-b",
        )


def test_profile_conversation_with_history_reports_missing_thread_binding(tmp_path):
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
        skill_source_root=REPO_ROOT,
        skill_manifest_path=REPO_ROOT / "server/manager/skills/catalog.json",
    )
    conversation = service.create_conversation(
        PRINCIPAL,
        PROFILE_ID,
        title="Persisted conversation",
    )
    supervisor = AgentAppServerSupervisor(service, codex_binary="codex")

    with pytest.raises(AgentAppServerError, match="thread binding is missing"):
        supervisor.conversation_items(
            PRINCIPAL,
            PROFILE_ID,
            conversation["conversation_id"],
        )


class _AppHandler(AgentAppServerRoutesMixin, AgentRoutesMixin):
    def __init__(self, service, supervisor, payload=None):
        self.state = SimpleNamespace(
            agent_app_server=supervisor,
            agent_profiles=service,
            server_id="public-1",
            client_state=SimpleNamespace(
                profiles=lambda _principal: [
                    {
                        "profile_id": PROFILE_ID,
                        "server": {"server_id": "public-1"},
                    }
                ]
            ),
        )
        self._service = service
        self._payload = payload or {}
        self.wfile = io.BytesIO()
        self.response_status = None
        self.response_headers = {}

    def _session(self):
        return {"username": PRINCIPAL}

    def _json_body(self, _maximum):
        return self._payload

    def send_response(self, status):
        self.response_status = status

    def send_header(self, name, value):
        self.response_headers[name] = value

    def end_headers(self):
        return None


class _SSESupervisor:
    def __init__(self):
        self.calls = []

    def status(self, _principal, _profile_id):
        return {
            "running": True,
            "active_conversation_id": "conversation-live",
        }

    def events(self, _principal, _profile_id, *, after, timeout):
        self.calls.append((after, timeout))
        if len(self.calls) == 1:
            return [
                {
                    "sequence": 7,
                    "payload": {
                        "method": "item/agentMessage/delta",
                        "params": {"delta": "hello"},
                    },
                },
                {
                    "sequence": 8,
                    "payload": {
                        "method": "item/completed",
                        "params": {
                            "item": {
                                "id": "command-1",
                                "type": "commandExecution",
                                "command": "factortester product-library list",
                                "aggregatedOutput": "98 products",
                                "cwd": "/research/maxc",
                                "status": "completed",
                            }
                        },
                    },
                },
            ]
        raise ConnectionResetError


class _StoppedSSESupervisor(_SSESupervisor):
    def status(self, _principal, _profile_id):
        return {
            "running": False,
            "event_sequence": 8,
            "active_conversation_id": "conversation-live",
        }

    def events(self, _principal, _profile_id, *, after, timeout):
        self.calls.append((after, timeout))
        if len(self.calls) == 1:
            return [{
                "sequence": 8,
                "payload": {
                    "method": "item/completed",
                    "params": {
                        "item": {
                            "id": "final-1",
                            "type": "agentMessage",
                            "text": "finished before SSE reconnected",
                        },
                    },
                },
            }]
        return []


def _response(handler):
    raw = handler.wfile.getvalue()
    content_length = int(handler.response_headers.get("Content-Length", len(raw)))
    return json.loads(raw[:content_length].decode("utf-8"))


def test_profile_agent_sse_uses_incremental_http11_chunks():
    supervisor = _SSESupervisor()
    handler = _AppHandler(None, supervisor)

    handler._stream_agent_events(
        supervisor,
        PRINCIPAL,
        PROFILE_ID,
        after=0,
    )

    raw = handler.wfile.getvalue()
    assert handler.protocol_version == "HTTP/1.1"
    assert handler.response_headers["Transfer-Encoding"] == "chunked"
    assert handler.response_headers["Content-Encoding"] == "identity"
    assert handler.response_headers["Cache-Control"] == (
        "no-cache, no-store, no-transform"
    )
    sse_payload = b'id: 7\ndata: {"method": "item/agentMessage/delta", '
    assert sse_payload in raw
    chunk_length, chunk_body = raw.split(b"\r\n", 1)
    assert int(chunk_length, 16) > 0
    assert chunk_body.startswith(sse_payload)
    assert b'"chatkit_item": {"id": "command-1"' in raw
    assert b'"type": "workflow"' in raw
    assert b'"summary": {"title": "factortester product-library list"}' in raw
    assert b'"cwd": "/research/maxc"' in raw
    assert supervisor.calls[0][0] == 0


def test_profile_agent_sse_replays_final_event_after_agent_stops():
    supervisor = _StoppedSSESupervisor()
    handler = _AppHandler(None, supervisor)

    handler._stream_agent_events(
        supervisor,
        PRINCIPAL,
        PROFILE_ID,
        after=5,
    )

    raw = handler.wfile.getvalue()
    assert handler.response_status == 200
    assert b'id: 8\ndata: {"method": "item/completed"' in raw
    assert b'finished before SSE reconnected' in raw
    assert supervisor.calls == [(5, 5.0), (8, 5.0)]


def test_profile_agent_final_item_clears_processing_conversation():
    supervisor = AgentAppServerSupervisor.__new__(AgentAppServerSupervisor)
    supervisor._lock = threading.RLock()
    key = (PRINCIPAL, PROFILE_ID)
    supervisor._processing_turns = {
        key: {"conversation_id": "conversation-live"},
    }
    observed = []
    observer = SimpleNamespace(observe=observed.append)

    payload = {
        "method": "item/completed",
        "params": {"item": {"id": "final", "type": "agentMessage"}},
    }
    supervisor._observe_runtime_event(key, observer, payload)

    assert observed == [payload]
    assert key not in supervisor._processing_turns


def test_profile_agent_binds_provider_turn_id_from_runtime_event():
    supervisor = AgentAppServerSupervisor.__new__(AgentAppServerSupervisor)
    supervisor._lock = threading.RLock()
    key = (PRINCIPAL, PROFILE_ID)
    supervisor._processing_turns = {
        key: {"conversation_id": "conversation-live", "event_after": 0},
    }
    observer = SimpleNamespace(observe=lambda _payload: None)

    supervisor._observe_runtime_event(
        key,
        observer,
        {
            "method": "thread/tokenUsage/updated",
            "params": {"turnId": "01a04bc2-09d8-7c81-a60c-c369c19c2ca5"},
        },
    )

    assert supervisor._processing_turns[key]["turn_id"] == (
        "01a04bc2-09d8-7c81-a60c-c369c19c2ca5"
    )


def test_profile_agent_turn_completed_clears_processing_turn():
    supervisor = AgentAppServerSupervisor.__new__(AgentAppServerSupervisor)
    supervisor._lock = threading.RLock()
    key = (PRINCIPAL, PROFILE_ID)
    supervisor._processing_turns = {
        key: {"conversation_id": "conversation-live", "turn_id": "turn-live"},
    }
    observer = SimpleNamespace(observe=lambda _payload: None)

    supervisor._observe_runtime_event(
        key,
        observer,
        {
            "method": "turn/completed",
            "params": {"turn": {"id": "turn-live", "status": "completed"}},
        },
    )

    assert key not in supervisor._processing_turns


def test_profile_agent_late_old_turn_completion_preserves_new_turn():
    supervisor = AgentAppServerSupervisor.__new__(AgentAppServerSupervisor)
    supervisor._lock = threading.RLock()
    key = (PRINCIPAL, PROFILE_ID)
    supervisor._processing_turns = {
        key: {"conversation_id": "conversation-live", "turn_id": "turn-new"},
    }
    observer = SimpleNamespace(observe=lambda _payload: None)

    supervisor._observe_runtime_event(
        key,
        observer,
        {
            "method": "turn/completed",
            "params": {"turn": {"id": "turn-old", "status": "completed"}},
        },
    )

    assert supervisor._processing_turns[key]["turn_id"] == "turn-new"


def test_profile_agent_http_routes_start_and_proxy_authenticated_session(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(
        "FACTORTESTER_CLI", _fake_factor_tester(tmp_path / "factortester")
    )
    monkeypatch.setattr(AgentProviderHealth, "test", _provider_health_ok)
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
        skill_source_root=REPO_ROOT,
        skill_manifest_path=REPO_ROOT / "server/manager/skills/catalog.json",
    )
    service.bind_runtime(
        PRINCIPAL,
        PROFILE_ID,
        runtime_kind="server",
        executor_id="public-1",
    )
    provider = service.save_provider(
        PRINCIPAL,
        {
            "label": "fake provider",
            "runtime_kind": "server",
            "base_url": "https://api.example.test/v1",
            "default_model": "research-model",
            "token": "server-secret-token",
        },
    )
    service.claim(PRINCIPAL, PROFILE_ID, provider_id=provider["provider_id"])
    supervisor = AgentAppServerSupervisor(
        service,
        codex_binary=_fake_codex(tmp_path / "fake-codex", history=True),
    )

    handler = _AppHandler(service, supervisor, {"profile_id": PROFILE_ID})
    assert handler._post_agent_app_routes(urlparse("/api/client/profile-agent/start"))
    assert handler.response_status == 200
    assert _response(handler)["status"]["ready"] is True

    conversation = service.create_conversation(PRINCIPAL, PROFILE_ID)
    handler = _AppHandler(
        service,
        supervisor,
        {
            "profile_id": PROFILE_ID,
            "conversation_id": conversation["conversation_id"],
            "method": "thread/start",
            "params": {},
        },
    )
    assert handler._post_agent_app_routes(urlparse("/api/client/profile-agent/rpc"))

    handler = _AppHandler(service, supervisor)
    assert handler._get_agent_app_routes(
        urlparse(f"/api/client/profile-agent/conversations?profile_id={PROFILE_ID}"),
    )
    listed = _response(handler)["conversations"]
    assert listed[0]["conversation_id"] == conversation["conversation_id"]
    assert listed[0]["model_id"] == "research-model"
    assert "principal" not in listed[0]
    assert "provider_id" not in listed[0]

    original_capabilities = supervisor.model_capabilities
    catalog_refreshes = []
    monkeypatch.setattr(
        supervisor,
        "model_capabilities",
        lambda principal, profile_id, *, refresh=False: (
            catalog_refreshes.append(refresh)
            or original_capabilities(principal, profile_id, refresh=refresh)
        ),
    )
    handler = _AppHandler(
        service,
        supervisor,
        {
            "profile_id": PROFILE_ID,
            "conversation_id": conversation["conversation_id"],
            "model_id": "research-model-fast",
            "reasoning_effort": "high",
            "service_tier": "fast",
            "refresh_catalog": True,
        },
    )
    assert handler._post_agent_app_routes(
        urlparse(
            "/api/client/profile-agent/conversations/settings",
        )
    )
    settings = _response(handler)["conversation"]
    assert settings["model_id"] == "research-model-fast"
    assert settings["reasoning_effort"] == "high"
    assert settings["service_tier"] == "fast"
    assert catalog_refreshes[-1] is True

    handler = _AppHandler(service, supervisor)
    assert handler._get_agent_app_routes(
        urlparse(
            f"/api/client/profile-agent/models?profile_id={PROFILE_ID}",
        )
    )
    catalog = _response(handler)
    assert catalog["latency_ms"] == 125
    fast = next(
        item for item in catalog["models"] if item["id"] == "research-model-fast"
    )
    assert [item["id"] for item in fast["reasoning_efforts"]] == ["medium", "high"]
    assert [item["id"] for item in fast["service_tiers"]] == ["fast"]

    handler = _AppHandler(
        service,
        supervisor,
        {
            "profile_id": PROFILE_ID,
            "conversation_id": conversation["conversation_id"],
            "method": "turn/start",
            "params": {
                "prompt": "hello",
                "threadId": "provider-thread-1",
                "skill_ids": [],
            },
        },
    )
    assert handler._post_agent_app_routes(urlparse("/api/client/profile-agent/rpc"))
    turn = _response(handler)["response"]["result"]
    assert turn["accepted"] == "turn/start"
    assert turn["params"]["model"] == "research-model-fast"

    handler = _AppHandler(service, supervisor)
    assert handler._get_agent_app_routes(
        urlparse(
            "/api/client/profile-agent/conversation-items"
            f"?profile_id={PROFILE_ID}"
            f"&conversation_id={conversation['conversation_id']}"
            "&limit=7&view=timeline",
        )
    )
    history = _response(handler)
    assert history["success"] is True
    assert history["turn_count"] == 1
    assert history["has_more"] is False
    assert [item["type"] for item in history["items"]] == [
        "assistant_message",
        "user_message",
    ]

    handler = _AppHandler(service, supervisor)
    assert handler._get_agent_app_routes(
        urlparse(f"/api/client/profile-agent?profile_id={PROFILE_ID}"),
    )
    assert _response(handler)["status"]["running"] is True
    supervisor.stop_all()


def test_profile_agent_routes_reject_client_managed_profile(tmp_path):
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
        skill_source_root=REPO_ROOT,
        skill_manifest_path=REPO_ROOT / "server/manager/skills/catalog.json",
    )
    service.bind_runtime(
        PRINCIPAL,
        PROFILE_ID,
        runtime_kind="client",
        executor_id="client-device-1",
    )
    supervisor = AgentAppServerSupervisor(service)

    handler = _AppHandler(service, supervisor)
    assert handler._get_agent_app_routes(
        urlparse(f"/api/client/profile-agent?profile_id={PROFILE_ID}"),
    )

    assert handler.response_status == 400
    assert "not bound to a server runtime" in _response(handler)["error"]


def test_profile_agent_runtime_events_update_conversation_metadata(tmp_path):
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
        skill_source_root=REPO_ROOT,
        skill_manifest_path=REPO_ROOT / "server/manager/skills/catalog.json",
    )
    conversation = service.conversation_store.create(PRINCIPAL, PROFILE_ID)
    service.conversation_store.save_thread(
        PRINCIPAL,
        PROFILE_ID,
        conversation["conversation_id"],
        "provider-thread-1",
    )
    observer = AgentConversationRuntimeObserver(
        service.conversation_store,
        PRINCIPAL,
        PROFILE_ID,
    )

    observer.observe(
        {
            "method": "thread/tokenUsage/updated",
            "params": {
                "threadId": "provider-thread-1",
                "turnId": "turn-1",
                "tokenUsage": {
                    "modelContextWindow": 200000,
                    "last": {"totalTokens": 12000},
                    "total": {"totalTokens": 45000},
                },
            },
        }
    )
    observer.observe(
        {
            "method": "thread/settings/updated",
            "params": {
                "threadId": "provider-thread-1",
                "threadSettings": {"model": "research-model"},
            },
        }
    )
    observer.observe(
        {
            "method": "model/rerouted",
            "params": {
                "threadId": "provider-thread-1",
                "turnId": "turn-1",
                "fromModel": "research-model",
                "toModel": "research-model-safe",
            },
        }
    )
    compaction = {
        "method": "thread/compacted",
        "params": {"threadId": "provider-thread-1", "turnId": "turn-1"},
    }
    observer.observe(compaction)
    observer.observe(compaction)
    context_compaction = {
        "method": "item/completed",
        "params": {
            "threadId": "provider-thread-1",
            "turnId": "turn-2",
            "item": {"id": "compaction-2", "type": "contextCompaction"},
        },
    }
    observer.observe(context_compaction)
    observer.observe(context_compaction)

    updated = service.conversation_store.get(
        PRINCIPAL,
        PROFILE_ID,
        conversation["conversation_id"],
    )
    assert updated is not None
    assert updated["actual_model"] == "research-model-safe"
    assert updated["model_context_window"] == 200000
    assert updated["last_tokens"] == 12000
    assert updated["total_tokens"] == 45000
    assert updated["compaction_count"] == 2


def test_provider_test_route_returns_safe_health_result(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentProviderHealth, "test", _provider_health_ok)
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
        skill_source_root=REPO_ROOT,
        skill_manifest_path=REPO_ROOT / "server/manager/skills/catalog.json",
    )
    handler = _AppHandler(
        service,
        None,
        {
            "label": "temporary provider",
            "runtime_kind": "server",
            "protocol": "openai_compatible",
            "base_url": "https://api.example.test/v1",
            "default_model": "research-model",
            "token": "secret-must-not-return",
        },
    )
    assert handler._post_agent_routes(urlparse("/api/client/agent-models/test"))
    payload = _response(handler)
    assert payload["success"] is True
    assert payload["test"]["model_available"] is True
    assert "secret-must-not-return" not in json.dumps(payload)


def test_provider_test_route_returns_stable_error_classification(tmp_path, monkeypatch):
    def reject(_provider):
        raise AgentProviderHealthError(
            "provider rejected the API key (HTTP 401)",
            code="credential_rejected",
        )

    monkeypatch.setattr(AgentProviderHealth, "test", reject)
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
        skill_source_root=REPO_ROOT,
        skill_manifest_path=REPO_ROOT / "server/manager/skills/catalog.json",
    )
    handler = _AppHandler(
        service,
        None,
        {
            "label": "temporary provider",
            "runtime_kind": "server",
            "protocol": "openai_responses",
            "base_url": "https://api.example.test/v1",
            "default_model": "research-model",
            "token": "secret-must-not-return",
        },
    )

    assert handler._post_agent_routes(urlparse("/api/client/agent-models/test"))
    payload = _response(handler)
    assert payload["success"] is False
    assert payload["code"] == "credential_rejected"
    assert "secret-must-not-return" not in json.dumps(payload)


def test_provider_preflight_failure_blocks_process_start(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "FACTORTESTER_CLI", _fake_factor_tester(tmp_path / "factortester")
    )

    def reject(_provider):
        raise AgentProviderHealthError("provider rejected the connection (HTTP 401)")

    monkeypatch.setattr(AgentProviderHealth, "test", reject)
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
        skill_source_root=REPO_ROOT,
        skill_manifest_path=REPO_ROOT / "server/manager/skills/catalog.json",
    )
    service.bind_runtime(
        PRINCIPAL,
        PROFILE_ID,
        runtime_kind="server",
        executor_id="public-1",
    )
    provider = service.save_provider(
        PRINCIPAL,
        {
            "label": "rejected provider",
            "runtime_kind": "server",
            "protocol": "openai_compatible",
            "base_url": "https://api.example.test/v1",
            "default_model": "research-model",
            "token": "server-secret-token",
        },
    )
    service.claim(PRINCIPAL, PROFILE_ID, provider_id=provider["provider_id"])
    supervisor = AgentAppServerSupervisor(
        service,
        codex_binary=_fake_codex(tmp_path / "fake-codex"),
    )

    with pytest.raises(AgentAppServerError, match="provider preflight failed"):
        supervisor.start(PRINCIPAL, PROFILE_ID)
    assert supervisor.status(PRINCIPAL, PROFILE_ID)["running"] is False


def test_missing_factor_tester_cli_blocks_process_start(tmp_path, monkeypatch):
    monkeypatch.delenv("FACTORTESTER_CLI", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    monkeypatch.setattr(AgentProviderHealth, "test", _provider_health_ok)
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
        skill_source_root=REPO_ROOT,
        skill_manifest_path=REPO_ROOT / "server/manager/skills/catalog.json",
    )
    service.bind_runtime(
        PRINCIPAL,
        PROFILE_ID,
        runtime_kind="server",
        executor_id="public-1",
    )
    provider = service.save_provider(
        PRINCIPAL,
        {
            "label": "provider",
            "runtime_kind": "server",
            "protocol": "openai_compatible",
            "base_url": "https://api.example.test/v1",
            "default_model": "research-model",
            "token": "server-secret-token",
        },
    )
    service.claim(PRINCIPAL, PROFILE_ID, provider_id=provider["provider_id"])
    supervisor = AgentAppServerSupervisor(
        service,
        codex_binary=_fake_codex(tmp_path / "fake-codex"),
    )

    with pytest.raises(AgentAppServerError, match="FactorTester CLI") as error:
        supervisor.start(PRINCIPAL, PROFILE_ID)
    assert error.value.code == "runtime_missing"
    assert supervisor.status(PRINCIPAL, PROFILE_ID)["running"] is False
