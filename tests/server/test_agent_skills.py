from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from server.manager.http.agent_routes import AgentRoutesMixin
from server.manager.services.agent_profiles import AgentProfileService
from server.manager.services.agent_skill_catalog import AgentSkillCatalog
from server.manager.services.agent_workspace import profile_workspace_relative_path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRINCIPAL = "GTHT@MaxJJW@1234"
PROFILE_ID = "profile-main"


def test_skill_catalog_only_exposes_profile_audience_and_hides_paths():
    catalog = AgentSkillCatalog(
        REPO_ROOT,
        REPO_ROOT / "server/manager/skills/catalog.json",
    )

    definitions = catalog.definitions("server")
    assert [item["skill_id"] for item in definitions] == [
        "factortester-research",
        "research-obligation-cycle",
    ]
    public = catalog.public_definitions("server")
    assert all("path" not in item for item in public)
    assert all("relative_path" not in item for item in public)


def test_skill_catalog_supports_client_and_server_runtime_boundaries():
    catalog = AgentSkillCatalog(
        REPO_ROOT,
        REPO_ROOT / "server/manager/skills/catalog.json",
    )

    assert catalog.definitions("client") == []
    assert [item["label"] for item in catalog.public_definitions("server")] == [
        "FactorTester 研究",
        "研究义务周期",
    ]


def test_profile_skill_selection_is_local_and_validated(tmp_path):
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "agent-provider.key",
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

    initial = service.profile_skills(PRINCIPAL, PROFILE_ID)
    assert initial["runtime_kind"] == "server"
    assert all(item["selected"] is False for item in initial["skills"])

    saved = service.set_profile_skills(
        PRINCIPAL,
        PROFILE_ID,
        ["research-obligation-cycle", "factortester-research"],
    )
    assert saved["selected_skill_ids"] == [
        "factortester-research",
        "research-obligation-cycle",
    ]
    bindings = service.selected_skill_bindings(PRINCIPAL, PROFILE_ID)
    assert [item["skill_id"] for item in bindings] == saved["selected_skill_ids"]
    assert all((Path(item["path"]) / "SKILL.md").is_file() for item in bindings)

    provider = service.save_provider(
        PRINCIPAL,
        {
            "label": "server provider",
            "runtime_kind": "server",
            "base_url": "https://api.example.test/v1",
            "default_model": "research-model",
            "token": "token",
        },
    )
    claim = service.claim(
        PRINCIPAL,
        PROFILE_ID,
        provider_id=provider["provider_id"],
        agent_id="agent-a",
    )
    assert claim["selected_skill_ids"] == saved["selected_skill_ids"]
    with pytest.raises(ValueError, match="release the active Agent"):
        service.set_profile_skills(PRINCIPAL, PROFILE_ID, [])
    service.release(PRINCIPAL, claim["claim"]["claim_id"], agent_id="agent-a")

    with pytest.raises(ValueError, match="not installed"):
        service.set_profile_skills(PRINCIPAL, PROFILE_ID, ["manager-admin"])


class _Handler(AgentRoutesMixin):
    def __init__(self, service, *, payload=None):
        self.state = SimpleNamespace(
            agent_profiles=service,
            server_id="public-1",
            client_state=SimpleNamespace(profiles=lambda _principal: [{
                "profile_id": PROFILE_ID,
                "server": {"server_id": "public-1"},
            }]),
        )
        self._payload = payload or {}
        self.response_status = None
        self.wfile = io.BytesIO()

    def _session(self):
        return {"username": PRINCIPAL}

    def _json_body(self, _maximum):
        return self._payload

    def _is_local_ftclient(self):
        return False

    def send_response(self, status):
        self.response_status = status

    def send_header(self, _name, _value):
        pass

    def end_headers(self):
        pass


def _body(handler):
    return json.loads(handler.wfile.getvalue().decode("utf-8"))


def test_profile_skill_routes_read_and_replace_selection(tmp_path):
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "agent-provider.key",
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
    handler = _Handler(service)
    assert handler._get_agent_routes(
        urlparse(f"/api/client/profile-skills?profile_id={PROFILE_ID}"),
    ) is True
    assert _body(handler)["skills"][0]["selected"] is False

    handler = _Handler(service, payload={
        "profile_id": PROFILE_ID,
        "skill_ids": ["factortester-research"],
    })
    assert handler._post_agent_routes(urlparse("/api/client/profile-skills")) is True
    assert handler.response_status == 200
    assert _body(handler)["selected_skill_ids"] == ["factortester-research"]


def test_profile_module_loads_skill_selector_after_manifest_entry():
    manifest = json.loads(
        (REPO_ROOT / "server/manager/web/module-manifest.json").read_text(
            encoding="utf-8",
        )
    )
    profile_scripts = manifest["groups"]["profile"]
    assert profile_scripts.index("profile/agent-skills.js") < profile_scripts.index(
        "profile/profiles.js"
    )
    source = (
        REPO_ROOT / "server/manager/web/profile/agent-skills.js"
    ).read_text(encoding="utf-8")
    assert "/api/client/profile-skills" in source
    assert "method: \"POST\"" in source
    assert "安装任意" not in source
