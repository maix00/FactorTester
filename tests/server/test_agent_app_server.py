from __future__ import annotations

import os
import io
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from server.manager.http.agent_app_routes import AgentAppServerRoutesMixin
from server.manager.http.agent_routes import AgentRoutesMixin
from server.manager.services.agent_app_server import AgentAppServerSupervisor
from server.manager.services.agent_app_server_errors import AgentAppServerError
from server.manager.services.agent_profiles import AgentProfileService
from server.manager.services.agent_workspace import profile_workspace_relative_path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRINCIPAL = "GTHT@MaxJJW@1234"
PROFILE_ID = "profile-main"


def _fake_codex(path: Path) -> str:
    path.write_text(
        """#!/usr/bin/env python3
import json
import sys

for raw in sys.stdin:
    request = json.loads(raw)
    method = request.get("method")
    if method == "skills/list":
        result = {"data": [{"cwd": request.get("params", {}).get("cwds", [""])[0], "skills": []}]}
    elif method == "initialize":
        result = {"userAgent": "fake-codex"}
    else:
        result = {"accepted": method}
    if "id" in request:
        sys.stdout.write(json.dumps({"id": request["id"], "result": result}) + "\\n")
        sys.stdout.flush()
""",
        encoding="utf-8",
    )
    os.chmod(path, 0o700)
    return str(path)


def test_server_profile_app_server_starts_and_forwards_jsonl(tmp_path):
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
    )

    status = supervisor.start(PRINCIPAL, PROFILE_ID)
    assert status["ready"] is True
    assert status["running"] is True
    response = supervisor.request(
        PRINCIPAL,
        PROFILE_ID,
        "turn/start",
        {"prompt": "hello", "skill_ids": []},
    )
    assert response["result"]["accepted"] == "turn/start"
    config_path = (
        tmp_path / "data" / profile_workspace_relative_path(PRINCIPAL, PROFILE_ID)
        / ".codex" / "config.toml"
    )
    config = config_path.read_text(encoding="utf-8")
    assert "research-model" in config
    assert "server-secret-token" not in config
    assert 'approval_policy = "never"' in config
    assert 'sandbox_mode = "workspace-write"' in config
    assert "sandbox_workspace_write.network_access = true" in config
    assert "ignore_default_excludes = false" in config
    assert supervisor.status(PRINCIPAL, PROFILE_ID)["pid"] is not None

    with pytest.raises(AgentAppServerError, match="policy override"):
        supervisor.request(
            PRINCIPAL,
            PROFILE_ID,
            "turn/start",
            {"prompt": "hello", "approvalPolicy": "never"},
        )
    with pytest.raises(AgentAppServerError, match="only text input"):
        supervisor.request(
            PRINCIPAL,
            PROFILE_ID,
            "turn/start",
            {
                "input": [{"type": "image", "path": "/etc/passwd"}],
            },
        )
    with pytest.raises(AgentAppServerError, match="Profile workspace"):
        supervisor.request(
            PRINCIPAL,
            PROFILE_ID,
            "thread/start",
            {"cwd": str(tmp_path)},
        )

    supervisor.stop(PRINCIPAL, PROFILE_ID)
    assert supervisor.status(PRINCIPAL, PROFILE_ID)["running"] is False
    assert claim["claim"]["agent_id"] == "agent-a"


class _AppHandler(AgentAppServerRoutesMixin, AgentRoutesMixin):
    def __init__(self, service, supervisor, payload=None):
        self.state = SimpleNamespace(
            agent_app_server=supervisor,
            server_id="public-1",
            client_state=SimpleNamespace(profiles=lambda _principal: [{
                "profile_id": PROFILE_ID,
                "server": {"server_id": "public-1"},
            }]),
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


def _response(handler):
    raw = handler.wfile.getvalue()
    content_length = int(handler.response_headers.get("Content-Length", len(raw)))
    return json.loads(raw[:content_length].decode("utf-8"))


def test_profile_agent_http_routes_start_and_proxy_authenticated_session(tmp_path):
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
        codex_binary=_fake_codex(tmp_path / "fake-codex"),
    )

    handler = _AppHandler(service, supervisor, {"profile_id": PROFILE_ID})
    assert handler._post_agent_app_routes(urlparse("/api/client/profile-agent/start"))
    assert handler.response_status == 200
    assert _response(handler)["status"]["ready"] is True

    handler = _AppHandler(service, supervisor, {
        "profile_id": PROFILE_ID,
        "method": "turn/start",
        "params": {"prompt": "hello", "skill_ids": []},
    })
    assert handler._post_agent_app_routes(urlparse("/api/client/profile-agent/rpc"))
    assert _response(handler)["response"]["result"]["accepted"] == "turn/start"

    handler = _AppHandler(service, supervisor)
    assert handler._get_agent_app_routes(
        urlparse(f"/api/client/profile-agent?profile_id={PROFILE_ID}"),
    )
    assert _response(handler)["status"]["running"] is True
    supervisor.stop_all()
