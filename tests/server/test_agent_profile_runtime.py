from __future__ import annotations

import sqlite3
import io
import json
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from server.manager.services.agent_profiles import AgentProfileService
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
