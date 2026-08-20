from __future__ import annotations

import sqlite3
import io
import json
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from server.manager.services.agent_profiles import AgentProfileService
from server.manager.services.agent_provider_health import AgentProviderHealth
from server.manager.http.agent_routes import AgentRoutesMixin
from server.manager.services.agent_workspace import (
    WORKSPACE_DIRECTORIES,
    profile_workspace_relative_path,
)
from server.manager.storage.agent_provider_store import (
    AgentProviderStore,
    ProviderStoreError,
)
from server.manager.storage.profile_runtime_store import (
    ProfileClaimConflict,
    ProfileRuntimeStore,
)


PRINCIPAL = "GTHT@MaxJJW@1234"
PROFILE_ID = "profile-main"


def test_provider_token_is_encrypted_and_server_urls_are_restricted(tmp_path):
    db_path = tmp_path / "manager.sqlite"
    key_path = tmp_path / "agent-provider.key"
    store = AgentProviderStore(db_path, key_path)

    saved = store.save(
        PRINCIPAL,
        {
            "label": "Research provider",
            "runtime_kind": "server",
            "server_id": "public-1",
            "protocol": "openai_compatible",
            "base_url": "https://api.example.test/v1",
            "default_model": "research-model",
            "token": "secret-token-value",
        },
    )

    assert saved["token_configured"] is True
    assert "token" not in saved
    assert store.get(PRINCIPAL, saved["provider_id"])["token_configured"] is True
    assert store.get(
        PRINCIPAL,
        saved["provider_id"],
        include_secret=True,
    )["secret"] == "secret-token-value"
    updated = store.save(
        PRINCIPAL,
        {
            "provider_id": saved["provider_id"],
            "label": "Renamed provider",
            "runtime_kind": "server",
            "server_id": "public-1",
            "protocol": "openai_compatible",
            "base_url": "https://api.example.test/v1",
            "default_model": "research-model-2",
        },
    )
    assert updated["created_at"] == saved["created_at"]
    assert updated["updated_at"] >= saved["updated_at"]
    assert key_path.stat().st_mode & 0o077 == 0

    assert saved["agent_runtime"] == "codex"
    assert saved["protocol"] == "openai_responses"
    assert saved["network_route"] == "direct"

    with sqlite3.connect(db_path) as connection:
        raw = connection.execute(
            "SELECT secret_blob FROM manager_agent_provider_connections",
        ).fetchone()[0]
    assert b"secret-token-value" not in raw

    with pytest.raises(ProviderStoreError, match="HTTPS"):
        store.save(
            PRINCIPAL,
            {
                "label": "unsafe",
                "runtime_kind": "server",
                "server_id": "public-1",
                "base_url": "http://api.example.test",
                "token": "x",
            },
        )


def test_provider_duplicate_keeps_secret_server_side_and_is_owner_scoped(tmp_path):
    store = AgentProviderStore(
        tmp_path / "manager.sqlite",
        tmp_path / "agent-provider.key",
    )
    original = store.save(
        PRINCIPAL,
        {
            "label": "Research provider",
            "runtime_kind": "server",
            "server_id": "public-1",
            "agent_runtime": "codex",
            "protocol": "anthropic_messages",
            "base_url": "https://api.example.test/v1",
            "default_model": "research-model",
            "token": "secret-token-value",
        },
    )

    duplicate = store.duplicate(PRINCIPAL, original["provider_id"])

    assert duplicate["provider_id"] != original["provider_id"]
    assert duplicate["label"] == "Research provider copy"
    assert duplicate["protocol"] == "anthropic_messages"
    assert duplicate["network_route"] == "direct"
    assert "secret" not in duplicate
    assert store.get(
        PRINCIPAL,
        duplicate["provider_id"],
        include_secret=True,
    )["secret"] == "secret-token-value"
    with pytest.raises(ProviderStoreError, match="not found"):
        store.duplicate("GTHT@Other@9999", original["provider_id"])
    with pytest.raises(ProviderStoreError, match="localhost"):
        store.save(
            PRINCIPAL,
            {
                "label": "unsafe",
                "runtime_kind": "server",
                "server_id": "public-1",
                "base_url": "https://localhost:9000",
                "token": "x",
            },
        )


def test_provider_persists_explicit_manager_proxy_route(tmp_path):
    store = AgentProviderStore(
        tmp_path / "manager.sqlite",
        tmp_path / "agent-provider.key",
    )

    saved = store.save(
        PRINCIPAL,
        {
            "label": "Proxied provider",
            "runtime_kind": "server",
            "server_id": "public-1",
            "protocol": "openai_responses",
            "base_url": "https://api.example.test/v1",
            "default_model": "research-model",
            "network_route": "manager_proxy",
            "token": "secret-token-value",
        },
    )

    assert saved["network_route"] == "manager_proxy"
    with pytest.raises(ProviderStoreError, match="network_route is unsupported"):
        store.save(
            PRINCIPAL,
            {
                "label": "Invalid route",
                "runtime_kind": "server",
                "server_id": "public-1",
                "protocol": "openai_responses",
                "base_url": "https://api.example.test/v1",
                "default_model": "research-model",
                "network_route": "automatic",
                "token": "secret-token-value",
            },
        )

    with pytest.raises(ProviderStoreError, match="client provider cannot use"):
        store.save(
            PRINCIPAL,
            {
                "label": "Invalid client proxy",
                "runtime_kind": "client",
                "protocol": "openai_responses",
                "base_url": "http://127.0.0.1:9000/v1",
                "default_model": "research-model",
                "network_route": "manager_proxy",
                "token": "secret-token-value",
            },
        )


@pytest.mark.parametrize(
    ("agent_runtime", "protocol"),
    [
        ("codex", "openai_responses"),
        ("codex", "openai_chat"),
        ("codex", "anthropic_messages"),
    ],
)
def test_provider_accepts_supported_agent_runtime_protocol_pairs(
    tmp_path, agent_runtime, protocol,
):
    store = AgentProviderStore(
        tmp_path / "manager.sqlite",
        tmp_path / "agent-provider.key",
    )

    saved = store.save(
        PRINCIPAL,
        {
            "label": f"{agent_runtime} provider",
            "runtime_kind": "server",
            "server_id": "public-1",
            "agent_runtime": agent_runtime,
            "protocol": protocol,
            "base_url": "https://api.example.test/v1",
            "default_model": "research-model",
            "token": "secret-token-value",
        },
    )

    assert saved["agent_runtime"] == agent_runtime
    assert saved["protocol"] == protocol


def test_provider_rejects_unsupported_agent_runtime(tmp_path):
    store = AgentProviderStore(
        tmp_path / "manager.sqlite",
        tmp_path / "agent-provider.key",
    )

    with pytest.raises(ProviderStoreError, match="unsupported"):
        store.save(
            PRINCIPAL,
            {
                "label": "invalid provider",
                "runtime_kind": "server",
                "server_id": "public-1",
                "agent_runtime": "gemini_cli",
                "protocol": "anthropic_messages",
                "base_url": "https://api.example.test/v1",
                "default_model": "research-model",
                "token": "secret-token-value",
            },
        )


def test_legacy_claim_provider_binding_is_frozen_once(tmp_path):
    store = ProfileRuntimeStore(tmp_path / "manager.sqlite")
    claim = store.claim(
        PRINCIPAL,
        PROFILE_ID,
        runtime_kind="server",
        executor_id="public-1",
        provider_id="provider-1",
        provider_config_version=0,
    )

    frozen = store.freeze_legacy_provider_binding(
        claim["claim_id"],
        provider_id="provider-1",
        agent_runtime="codex",
        provider_protocol="anthropic_messages",
        provider_model="claude-research",
        provider_config_version=123.5,
    )

    assert frozen["provider_protocol"] == "anthropic_messages"
    assert frozen["provider_model"] == "claude-research"
    assert frozen["provider_config_version"] == 123.5
    with pytest.raises(ProfileClaimConflict):
        store.freeze_legacy_provider_binding(
            claim["claim_id"],
            provider_id="provider-1",
            agent_runtime="codex",
            provider_protocol="openai_responses",
            provider_model="other-model",
            provider_config_version=456,
        )


def test_profile_has_one_runtime_and_one_live_claim(tmp_path):
    db_path = tmp_path / "manager.sqlite"
    service = AgentProfileService(
        db_path=db_path,
        provider_key_path=tmp_path / "agent-provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
    )
    provider = service.save_provider(
        PRINCIPAL,
        {
            "label": "Research provider",
            "runtime_kind": "server",
            "protocol": "openai_compatible",
            "base_url": "https://api.example.test/v1",
            "default_model": "research-model",
            "token": "secret-token-value",
        },
    )
    runtime = service.bind_runtime(
        PRINCIPAL,
        PROFILE_ID,
        runtime_kind="server",
        executor_id="public-1",
    )

    assert runtime["workspace_relpath"] == profile_workspace_relative_path(
        PRINCIPAL,
        PROFILE_ID,
    )
    workspace = tmp_path / "data" / runtime["workspace_relpath"]
    assert {path.name for path in workspace.iterdir()} == set(WORKSPACE_DIRECTORIES)

    first = service.claim(
        PRINCIPAL,
        PROFILE_ID,
        provider_id=provider["provider_id"],
        agent_id="agent-a",
    )
    assert first["claim"]["agent_runtime"] == "codex"
    assert first["claim"]["provider_protocol"] == "openai_responses"
    assert first["claim"]["provider_model"] == "research-model"
    assert first["claim"]["provider_config_version"] == provider["updated_at"]
    assert (workspace / ".codex").is_dir()
    same_agent = service.claim(
        PRINCIPAL,
        PROFILE_ID,
        provider_id=provider["provider_id"],
        agent_id="agent-a",
    )
    assert same_agent["claim"]["claim_id"] == first["claim"]["claim_id"]

    with pytest.raises(ProfileClaimConflict):
        service.claim(
            PRINCIPAL,
            PROFILE_ID,
            provider_id=provider["provider_id"],
            agent_id="agent-b",
        )

    assert service.release(
        PRINCIPAL,
        first["claim"]["claim_id"],
        agent_id="agent-a",
    )["released"] is True
    second = service.claim(
        PRINCIPAL,
        PROFILE_ID,
        provider_id=provider["provider_id"],
        agent_id="agent-b",
    )
    assert second["claim"]["agent_id"] == "agent-b"


def test_live_profile_claim_cannot_switch_its_frozen_provider_binding(tmp_path):
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "agent-provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
    )
    service.bind_runtime(
        PRINCIPAL,
        PROFILE_ID,
        runtime_kind="server",
        executor_id="public-1",
    )
    first_provider = service.save_provider(
        PRINCIPAL,
        {
            "label": "OpenAI",
            "runtime_kind": "server",
            "agent_runtime": "codex",
            "protocol": "openai_responses",
            "base_url": "https://api.openai.example/v1",
            "default_model": "gpt-research",
            "token": "openai-token",
        },
    )
    second_provider = service.save_provider(
        PRINCIPAL,
        {
            "label": "Anthropic",
            "runtime_kind": "server",
            "agent_runtime": "codex",
            "protocol": "anthropic_messages",
            "base_url": "https://api.anthropic.example/v1",
            "default_model": "claude-research",
            "token": "anthropic-token",
        },
    )
    service.claim(
        PRINCIPAL,
        PROFILE_ID,
        provider_id=first_provider["provider_id"],
        agent_id="agent-a",
    )

    with pytest.raises(ProfileClaimConflict):
        service.claim(
            PRINCIPAL,
            PROFILE_ID,
            provider_id=second_provider["provider_id"],
            agent_id="agent-a",
        )


def test_stale_claim_expires_without_creating_agent_temp_directory(tmp_path):
    store = ProfileRuntimeStore(tmp_path / "manager.sqlite")
    store.bind(
        PRINCIPAL,
        PROFILE_ID,
        runtime_kind="client",
        executor_id="device-1",
        workspace_relpath=profile_workspace_relative_path(PRINCIPAL, PROFILE_ID),
        now=100.0,
    )
    claim = store.claim(
        PRINCIPAL,
        PROFILE_ID,
        runtime_kind="client",
        executor_id="device-1",
        provider_id="provider-local",
        agent_id="agent-local",
        now=100.0,
        lease_seconds=10.0,
    )
    assert store.active_claim(
        PRINCIPAL,
        PROFILE_ID,
        now=105.0,
        lease_seconds=10.0,
    )["claim_id"] == claim["claim_id"]
    assert store.active_claim(
        PRINCIPAL,
        PROFILE_ID,
        now=111.0,
        lease_seconds=10.0,
    ) is None
    assert not list(tmp_path.rglob("agent-temp"))
    assert not list(tmp_path.rglob("agent-sessions"))


def test_paused_server_claim_survives_stop_and_can_resume(tmp_path):
    store = ProfileRuntimeStore(tmp_path / "manager.sqlite")
    store.bind(
        PRINCIPAL,
        PROFILE_ID,
        runtime_kind="server",
        executor_id="public-1",
        workspace_relpath=profile_workspace_relative_path(PRINCIPAL, PROFILE_ID),
        now=100.0,
    )
    claim = store.claim(
        PRINCIPAL,
        PROFILE_ID,
        runtime_kind="server",
        executor_id="public-1",
        provider_id="provider-server",
        agent_id="agent-server",
        now=100.0,
        lease_seconds=10.0,
    )

    assert store.pause(
        PRINCIPAL,
        claim["claim_id"],
        agent_id="agent-server",
        now=110.0,
    ) is True
    paused = store.active_claim(
        PRINCIPAL,
        PROFILE_ID,
        now=10_000.0,
        lease_seconds=10.0,
    )
    assert paused is not None
    assert paused["status"] == "stopped"

    resumed = store.heartbeat(
        PRINCIPAL,
        claim["claim_id"],
        agent_id="agent-server",
        now=10_001.0,
    )
    assert resumed["status"] == "claimed"


class _AgentRouteHandler(AgentRoutesMixin):
    def __init__(self, service, *, session=None, payload=None):
        self.state = SimpleNamespace(
            agent_profiles=service,
            server_id="public-1",
            client_state=SimpleNamespace(profiles=lambda _principal: [{
                "profile_id": PROFILE_ID,
                "server": {"server_id": "public-1"},
            }]),
        )
        self._session_value = session
        self._payload = payload or {}
        self.response_status = None
        self.response_headers = {}
        self.wfile = io.BytesIO()

    def _session(self):
        return self._session_value

    def _json_body(self, _maximum):
        return self._payload

    def _is_local_ftclient(self):
        return False

    def _bearer_token(self):
        return ""

    def send_response(self, status):
        self.response_status = status

    def send_header(self, name, value):
        self.response_headers[name] = value

    def end_headers(self):
        pass


def _route_payload(handler):
    return json.loads(handler.wfile.getvalue().decode("utf-8"))


def test_agent_routes_require_account_session_and_never_return_provider_token(tmp_path):
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "agent-provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
    )
    anonymous = _AgentRouteHandler(service)
    assert anonymous._get_agent_routes(urlparse("/api/client/agent-models")) is True
    assert anonymous.response_status == 401

    authenticated = _AgentRouteHandler(
        service,
        session={"username": PRINCIPAL, "role": "user"},
        payload={
            "label": "provider",
            "runtime_kind": "server",
            "protocol": "openai_compatible",
            "base_url": "https://api.example.test/v1",
            "default_model": "model",
            "token": "hidden-token",
        },
    )
    assert authenticated._post_agent_routes(
        urlparse("/api/client/agent-models"),
    ) is True
    response = _route_payload(authenticated)
    assert response["success"] is True
    assert response["provider"]["token_configured"] is True
    assert '"token":' not in json.dumps(response)

    listing = _AgentRouteHandler(
        service,
        session={"username": PRINCIPAL, "role": "user"},
    )
    assert listing._get_agent_routes(urlparse("/api/client/agent-models")) is True
    list_response = _route_payload(listing)
    capabilities = {
        item["runtime"]: item["protocols"]
        for item in list_response["runtime_capabilities"]
    }
    assert capabilities == {
        "codex": ["anthropic_messages", "openai_chat", "openai_responses"],
    }
    details = {
        item["protocol"]: item["transport"]
        for item in list_response["runtime_capabilities"][0]["protocol_details"]
    }
    assert details == {
        "anthropic_messages": "cc_switch",
        "openai_chat": "cc_switch",
        "openai_responses": "direct",
    }
    assert list_response["runtime_capabilities"][0]["network_route_details"] == [
        {"network_route": "direct", "label": "直接连接"},
        {
            "network_route": "manager_proxy",
            "label": "使用 Manager 网络代理",
        },
    ]

    duplicate = _AgentRouteHandler(
        service,
        session={"username": PRINCIPAL, "role": "user"},
    )
    provider_id = response["provider"]["provider_id"]
    assert duplicate._post_agent_routes(urlparse(
        f"/api/client/agent-models/{provider_id}/duplicate",
    )) is True
    duplicate_response = _route_payload(duplicate)
    assert duplicate_response["success"] is True
    assert duplicate_response["provider"]["provider_id"] != provider_id
    assert '"token":' not in json.dumps(duplicate_response)


def test_provider_test_route_classifies_unavailable_required_proxy(tmp_path):
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "agent-provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
        proxy_url_provider=lambda: "",
    )
    handler = _AgentRouteHandler(
        service,
        session={"username": PRINCIPAL, "role": "user"},
        payload={
            "label": "provider",
            "runtime_kind": "server",
            "protocol": "openai_responses",
            "base_url": "https://api.example.test/v1",
            "default_model": "model",
            "network_route": "manager_proxy",
            "token": "hidden-token",
        },
    )

    assert handler._post_agent_routes(
        urlparse("/api/client/agent-models/test"),
    ) is True
    response = _route_payload(handler)

    assert handler.response_status == 400
    assert response["code"] == "proxy_unavailable"


def test_agent_provider_listing_never_contacts_upstream_providers(
    tmp_path,
    monkeypatch,
):
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "agent-provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
    )
    service.save_provider(
        PRINCIPAL,
        {
            "label": "provider",
            "runtime_kind": "server",
            "protocol": "openai_responses",
            "base_url": "https://api.example.test/v1",
            "default_model": "model",
            "token": "hidden-token",
        },
    )

    def fail_if_health_check_runs(*_args, **_kwargs):
        raise AssertionError("provider listing must not contact an upstream API")

    monkeypatch.setattr(AgentProviderHealth, "test", fail_if_health_check_runs)
    listing = _AgentRouteHandler(
        service,
        session={"username": PRINCIPAL, "role": "user"},
    )

    assert listing._get_agent_routes(urlparse("/api/client/agent-models")) is True
    response = _route_payload(listing)
    assert response["success"] is True
    assert [item["label"] for item in response["providers"]] == ["provider"]
