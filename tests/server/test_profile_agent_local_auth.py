from __future__ import annotations

import json
import threading
from pathlib import Path

from server.manager.services.agent_app_server_launch import AgentAppServerLaunch
from server.manager.services.agent_skill_runtime import AgentSkillRuntime
from server.manager.state.sessions import SessionStateMixin
from server.manager.storage.session_store import ManagerSessionStore
from tools.cli.catalog.store import LocalCatalogStore


class _SessionState(SessionStateMixin):
    def __init__(self, path: Path) -> None:
        self.session_store = ManagerSessionStore(path)
        self._session_lock = threading.RLock()
        self._session_cleanup_at = 0.0
        self._sessions = self._load_sessions()
        self._agent_sessions: dict[str, dict[str, str]] = {}

    @staticmethod
    def _alias_for_principal(principal: str) -> str:
        return principal.rsplit("@", 1)[0]


def test_agent_session_is_bound_to_profile_and_revoked(tmp_path: Path) -> None:
    state = _SessionState(tmp_path / "sessions.sqlite")

    issued = state.issue_agent_session(
        "GTHT@MaxJJW@1",
        "profile-main",
        "claim-1",
    )

    assert state.agent_session_matches(
        issued["token"],
        "profile-main",
        "claim-1",
    )
    assert not state.agent_session_matches(
        issued["token"],
        "profile-other",
        "claim-1",
    )
    state.revoke_agent_session(issued["token"])
    assert not state.agent_session_matches(
        issued["token"],
        "profile-main",
        "claim-1",
    )


def test_agent_cli_files_are_private_and_cleaned(tmp_path: Path) -> None:
    runtime = AgentSkillRuntime(tmp_path / "workspace")
    launch = AgentAppServerLaunch(
        runtime=runtime,
        provider={"secret": "provider-secret"},
        codex_binary="codex",
        factor_tester_cli="factortester",
        factor_tester_auth={
            "base_url": "http://manager:7998",
            "token": "agent-session-token",
            "profile_id": "profile-main",
            "claim_id": "claim-1",
            "principal": "GTHT@MaxJJW@1",
        },
        proxy_url="http://127.0.0.1:7890",
    )

    launch.write_factor_tester_config()
    capability = json.loads(
        launch.factor_tester_capability_path.read_text(encoding="utf-8"),
    )
    config = json.loads(
        launch.factor_tester_config_path.read_text(encoding="utf-8"),
    )
    environment = launch.environment()

    assert config == {"base_url": "http://manager:7998"}
    assert capability["token"] == "agent-session-token"
    assert capability["profile_id"] == "profile-main"
    assert launch.factor_tester_capability_path.stat().st_mode & 0o077 == 0
    assert "manager" in environment["NO_PROXY"]
    assert (
        environment["FACTORTESTER_CONFIG"] == "/workspace/.codex/factor-tester-cli.json"
    )
    assert environment["FACTORTESTER_AGENT_CAPABILITY_FILE"] == (
        "/workspace/.codex/factor-tester-agent.json"
    )
    assert environment["FACTORTESTER_CLIENT_ROOT"] == "/workspace/.factortester-client"
    assert environment["FACTORTESTER_PROFILE"] == "profile-main"
    assert environment["FACTORTESTER_AGENT_TOKEN"] == "provider-secret"
    profile = json.loads(
        (
            runtime.factor_tester_client_root / "profiles" / "profile-main.json"
        ).read_text(encoding="utf-8")
    )
    assert profile["profile_id"] == "profile-main"
    assert profile["session_binding"]["principal_ref"] == "GTHT@MaxJJW@1"
    assert profile["workspace_root"] == "/workspace"
    catalog = LocalCatalogStore(runtime.factor_tester_client_root).initialize()
    assert catalog["schema_version"] > 0

    launch.cleanup_factor_tester_config()

    assert not launch.factor_tester_config_path.exists()
    assert not launch.factor_tester_capability_path.exists()


def test_agent_profiles_have_distinct_writable_client_roots(tmp_path: Path) -> None:
    first = AgentSkillRuntime(tmp_path / "first")
    second = AgentSkillRuntime(tmp_path / "second")

    first.environment()
    second.environment()

    assert first.factor_tester_client_root != second.factor_tester_client_root
    assert first.factor_tester_client_root.is_dir()
    assert second.factor_tester_client_root.is_dir()
