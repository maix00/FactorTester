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
from server.manager.services.agent_skill_protocol import AgentSkillProtocol
from server.manager.services.agent_skill_runtime import (
    AgentSkillRuntime,
    AgentSkillRuntimeError,
)
from server.manager.services.agent_workspace import profile_workspace_relative_path
from server.manager.services.profile_workspace_browser import (
    ProfileWorkspaceBrowser,
)


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
    assert [item["name"] for item in catalog.definitions("server")] == [
        "factortester-research-skill",
        "research-obligation-cycle",
    ]


def test_profile_codex_runtime_projects_only_selected_skills(tmp_path):
    catalog = AgentSkillCatalog(
        REPO_ROOT,
        REPO_ROOT / "server/manager/skills/catalog.json",
    )
    definitions = catalog.definitions("server")
    runtime = AgentSkillRuntime(tmp_path / "workspace")
    state = runtime.sync([definitions[0]])

    projection = runtime.skills_root / "factortester-research"
    assert projection.is_symlink()
    assert projection.resolve() == Path(definitions[0]["path"]).resolve()
    assert not (runtime.skills_root / "research-obligation-cycle").exists()
    assert [item["skill_id"] for item in state["skills"]] == [
        "factortester-research",
    ]
    assert runtime.command("/usr/local/bin/codex") == [
        "/usr/local/bin/codex", "app-server", "--listen", "stdio://",
    ]

    environment = runtime.environment({"HOME": "/host/home"})
    assert environment["CODEX_HOME"] == str(runtime.codex_home)
    assert environment["HOME"] == str(runtime.home_root)
    assert environment["XDG_CONFIG_HOME"] == str(runtime.config_root)


def test_profile_codex_runtime_updates_owned_links_without_touching_unknown_files(tmp_path):
    catalog = AgentSkillCatalog(
        REPO_ROOT,
        REPO_ROOT / "server/manager/skills/catalog.json",
    )
    definitions = catalog.definitions("server")
    runtime = AgentSkillRuntime(tmp_path / "workspace")
    runtime.sync([definitions[0]])
    unknown_file = runtime.skills_root / "keep-me.txt"
    unknown_file.write_text("user data", encoding="utf-8")

    runtime.sync([definitions[1]])
    assert not (runtime.skills_root / "factortester-research").exists()
    assert (runtime.skills_root / "research-obligation-cycle").is_symlink()
    assert unknown_file.read_text(encoding="utf-8") == "user data"


def test_profile_codex_runtime_rejects_projection_collision(tmp_path):
    catalog = AgentSkillCatalog(
        REPO_ROOT,
        REPO_ROOT / "server/manager/skills/catalog.json",
    )
    definition = catalog.definitions("server")[0]
    runtime = AgentSkillRuntime(tmp_path / "workspace")
    runtime._prepare_directories()
    collision = runtime.skills_root / definition["skill_id"]
    collision.write_text("not a link", encoding="utf-8")

    with pytest.raises(AgentSkillRuntimeError, match="unexpected Skill projection"):
        runtime.sync([definition])


def test_profile_codex_runtime_refuses_unowned_skill_directory(tmp_path):
    catalog = AgentSkillCatalog(
        REPO_ROOT,
        REPO_ROOT / "server/manager/skills/catalog.json",
    )
    definition = catalog.definitions("server")[0]
    runtime = AgentSkillRuntime(tmp_path / "workspace")
    runtime._prepare_directories()
    (runtime.skills_root / "unowned").mkdir()

    with pytest.raises(AgentSkillRuntimeError, match="unowned Skill directory"):
        runtime.sync([definition])


def test_profile_codex_runtime_keeps_codex_system_skills_directory(tmp_path):
    catalog = AgentSkillCatalog(
        REPO_ROOT,
        REPO_ROOT / "server/manager/skills/catalog.json",
    )
    definition = catalog.definitions("server")[0]
    runtime = AgentSkillRuntime(tmp_path / "workspace")
    runtime._prepare_directories()
    system_skills = runtime.skills_root / ".system"
    system_skills.mkdir()
    (system_skills / ".codex-system-skills.marker").write_text(
        "codex-system-skills", encoding="utf-8",
    )

    runtime.sync([definition])

    assert system_skills.is_dir()
    assert (system_skills / ".codex-system-skills.marker").is_file()


def test_profile_codex_runtime_rejects_unmarked_system_directory(tmp_path):
    catalog = AgentSkillCatalog(
        REPO_ROOT,
        REPO_ROOT / "server/manager/skills/catalog.json",
    )
    definition = catalog.definitions("server")[0]
    runtime = AgentSkillRuntime(tmp_path / "workspace")
    runtime._prepare_directories()
    (runtime.skills_root / ".system").mkdir()

    with pytest.raises(AgentSkillRuntimeError, match="unowned Skill directory"):
        runtime.sync([definition])


def test_profile_codex_skill_protocol_disables_unselected_and_builds_turn_input(tmp_path):
    catalog = AgentSkillCatalog(
        REPO_ROOT,
        REPO_ROOT / "server/manager/skills/catalog.json",
    )
    definitions = catalog.definitions("server")
    runtime = AgentSkillRuntime(tmp_path / "workspace")
    runtime.sync([definitions[0]])
    protocol = AgentSkillProtocol(runtime)
    selected_path = runtime.skills_root / definitions[0]["skill_id"] / "SKILL.md"

    requests = protocol.disable_unselected_requests([
        {"name": definitions[0]["name"], "path": str(selected_path)},
        {"name": "skill-installer", "path": str(tmp_path / "builtin/SKILL.md")},
        {"name": "other", "path": str(tmp_path / "builtin/SKILL.md")},
    ], first_request_id=20)
    assert requests == [{
        "jsonrpc": "2.0",
        "id": 20,
        "method": "skills/config/write",
        "params": {"path": str((tmp_path / "builtin/SKILL.md").resolve()), "enabled": False},
    }]
    assert protocol.enable_selected_requests([
        {"path": str(selected_path), "enabled": False},
    ]) == [{
        "jsonrpc": "2.0",
        "id": 1,
        "method": "skills/config/write",
        "params": {"path": str(selected_path.resolve()), "enabled": True},
    }]
    assert protocol.skills_list_params() == {
        "cwds": [str(runtime.workspace_root)],
        "forceReload": True,
    }
    assert AgentSkillProtocol.skills_from_response({
        "result": {"data": [{"cwd": "/tmp", "skills": [{"name": "one"}]}]},
    }) == [{"name": "one"}]
    turn_input = protocol.turn_skill_input("factortester-research")
    assert turn_input["type"] == "skill"
    assert turn_input["name"] == "factortester-research-skill"
    assert Path(turn_input["path"]) == selected_path

    with pytest.raises(ValueError, match="not selected"):
        protocol.turn_skill_input("research-obligation-cycle")


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
    workspace = tmp_path / "data" / profile_workspace_relative_path(PRINCIPAL, PROFILE_ID)
    assert (workspace / ".codex/skills/factortester-research").is_symlink()
    assert (workspace / ".codex/skills/research-obligation-cycle").is_symlink()

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


def test_server_runtime_binding_and_empty_claim_do_not_require_skill_files(tmp_path):
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "agent-provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
        skill_source_root=tmp_path / "image-without-skills",
    )

    runtime = service.bind_runtime(
        PRINCIPAL,
        PROFILE_ID,
        runtime_kind="server",
        executor_id="public-1",
    )
    workspace = tmp_path / "data" / runtime["workspace_relpath"]
    assert (workspace / "research").is_dir()
    assert service.selected_skill_bindings(PRINCIPAL, PROFILE_ID) == []

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
    assert claim["selected_skill_ids"] == []


def test_profile_workspace_browser_hides_sensitive_paths_and_hashes_files(tmp_path):
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "agent-provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
    )
    runtime = service.bind_runtime(
        PRINCIPAL,
        PROFILE_ID,
        runtime_kind="server",
        executor_id="public-1",
    )
    workspace = tmp_path / "data" / runtime["workspace_relpath"]
    (workspace / "research" / "notes.txt").write_text("hello", encoding="utf-8")
    (workspace / "research" / ".env").write_text("secret", encoding="utf-8")
    (workspace / ".codex").mkdir()

    browser = ProfileWorkspaceBrowser(
        data_root=tmp_path / "data",
        runtime_store=service.runtime_store,
        server_id="public-1",
    )
    root = browser.list(PRINCIPAL, PROFILE_ID)
    assert {item["name"] for item in root["entries"]} == {
        "factor-worktree", "strategy-worktree", "research", "reports", "manifests",
    }
    research = browser.list(PRINCIPAL, PROFILE_ID, "research")
    assert [item["name"] for item in research["entries"]] == ["notes.txt"]
    metadata = browser.file_metadata(PRINCIPAL, PROFILE_ID, "research/notes.txt")
    assert metadata["size_bytes"] == 5
    assert metadata["sha256"] == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


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


def test_profile_workspace_route_lists_only_safe_entries(tmp_path):
    service = AgentProfileService(
        db_path=tmp_path / "manager.sqlite",
        provider_key_path=tmp_path / "agent-provider.key",
        data_root=tmp_path / "data",
        server_id="public-1",
    )
    runtime = service.bind_runtime(
        PRINCIPAL,
        PROFILE_ID,
        runtime_kind="server",
        executor_id="public-1",
    )
    workspace = tmp_path / "data" / runtime["workspace_relpath"]
    (workspace / "research" / "notes.txt").write_text("hello", encoding="utf-8")

    handler = _Handler(service)
    assert handler._get_agent_routes(urlparse(
        f"/api/client/profile-workspace?profile_id={PROFILE_ID}&path=research",
    )) is True
    payload = _body(handler)
    assert payload["path"] == "research"
    assert payload["entries"] == [{
        "name": "notes.txt",
        "path": "research/notes.txt",
        "kind": "file",
        "size_bytes": 5,
        "downloadable": True,
    }]


def test_profile_module_loads_skill_selector_after_manifest_entry():
    manifest = json.loads(
        (REPO_ROOT / "server/manager/web/module-manifest.json").read_text(
            encoding="utf-8",
        )
    )
    profile_scripts = manifest["groups"]["profile"]
    assert "profile/workspace-browser.js" in manifest["scripts"]
    assert "profile/workspace-browser.js" in profile_scripts
    assert profile_scripts.index("profile/agent-skills.js") < profile_scripts.index(
        "profile/profiles.js"
    )
    assert profile_scripts.index("profile/agent-chat.js") < profile_scripts.index(
        "profile/profiles.js"
    )
    source = (
        REPO_ROOT / "server/manager/web/profile/agent-skills.js"
    ).read_text(encoding="utf-8")
    assert "/api/client/profile-skills" in source
    assert "method: \"POST\"" in source
    assert "安装任意" not in source
    chat_source = (
        REPO_ROOT / "server/manager/web/profile/agent-chat.js"
    ).read_text(encoding="utf-8")
    assert "/api/client/profile-agent/start" in chat_source
    assert "openai-chatkit" in chat_source
    assert "FTProfileChatKit" in chat_source
    assert "disabled: Boolean(options.readOnly)" not in chat_source
    assert "profile-chatkit-readonly-composer" in chat_source
    assert "不能发送问题" in chat_source
    assert "options.settingsHost?.replaceChildren(runtimeControls.element)" in chat_source
    assert "host.replaceChildren(chatStage)" in chat_source
    assert "chatSlot.replaceChildren(target)" not in chat_source
    assert 'context.t("结果")' not in chat_source
    assert 'context.t("过程")' not in chat_source
    assert 'context.t("启动 Agent")' not in chat_source
    assert 'context.t("停止 Agent")' not in chat_source
    assert "fetch: adapter.fetch" in chat_source
    protocol_source = (
        REPO_ROOT / "server/manager/web/profile/chatkit-protocol.js"
    ).read_text(encoding="utf-8")
    assert "FTProfileChatKitProtocol" in protocol_source
    adapter_source = (
        REPO_ROOT / "server/manager/web/profile/chatkit-adapter.js"
    ).read_text(encoding="utf-8")
    assert "https://cdn.platform.openai.com/deployments/chatkit/chatkit.js" in adapter_source
    assert "FTProfileChatKitProtocol" in adapter_source
    assert "params?.conversation_id" in adapter_source
    assert "params?.thread?.conversation_id" in adapter_source
    assert "P.historyTimestamp" in adapter_source
    stream_source = (
        REPO_ROOT / "server/manager/web/profile/chatkit-stream.js"
    ).read_text(encoding="utf-8")
    assert "/api/client/profile-agent/events" in stream_source
    assert "FTProfileChatKitProtocol" in stream_source
    assert "alignEventCursor" in stream_source
    assert "eventStream = openEventStream" in stream_source
    assert stream_source.index(
        "let eventStream = openEventStream(state, controller, signal);"
    ) < stream_source.index(
        'rpc(state, "turn/start"'
    )
    assert "event.lastEventId" in stream_source
    assert "eventTurnID" in protocol_source
    assert profile_scripts.index("profile/chatkit-protocol.js") < profile_scripts.index(
        "profile/chatkit-conversations.js"
    )
    assert profile_scripts.index("profile/chatkit-conversations.js") < profile_scripts.index(
        "profile/agent-runtime-controls.js"
    )
    assert profile_scripts.index("profile/agent-runtime-controls.js") < profile_scripts.index(
        "profile/chatkit-stream.js"
    )
    assert profile_scripts.index("profile/chatkit-stream.js") < profile_scripts.index(
        "profile/chatkit-adapter.js"
    )
    assert "profile/chatkit-conversations.js" in profile_scripts
    assert "profile/chatkit-stream.js" in profile_scripts
    assert "profile/chatkit-adapter.js" in profile_scripts
    assert profile_scripts.index("profile/chatkit-adapter.js") < profile_scripts.index(
        "profile/agent-chat.js"
    )
