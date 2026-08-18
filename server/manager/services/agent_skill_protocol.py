"""Codex app-server JSON-RPC helpers for Profile Skill policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from server.manager.services.agent_skill_runtime import AgentSkillRuntime


class AgentSkillProtocolError(ValueError):
    """A Skill policy cannot be represented in the app-server protocol."""


class AgentSkillProtocol:
    """Build the internal app-server requests for one prepared Profile."""

    def __init__(self, runtime: AgentSkillRuntime) -> None:
        self.runtime = runtime

    def skills_list_params(self) -> dict[str, Any]:
        return {
            "cwds": [str(self.runtime.workspace_root)],
            "forceReload": True,
        }

    @staticmethod
    def _path(value: object) -> Path | None:
        text = str(value or "").strip()
        if not text:
            return None
        return Path(text).expanduser().resolve()

    def _allowed_paths(self) -> set[Path]:
        # The current Codex release reports the canonical source path for a
        # projected symlink.  Keep both forms accepted for forward/backward
        # compatibility with app-server versions that retain the symlink.
        result: set[Path] = set()
        for skill_id in self.runtime.selected_bindings():
            projection = self.runtime.projected_skill_path(skill_id)
            result.add(projection.resolve())
            result.add(projection)
        return result

    def disable_unselected_requests(
        self,
        skills: Iterable[Mapping[str, object]],
        *,
        first_request_id: int = 1,
    ) -> list[dict[str, Any]]:
        """Disable every discovered Skill that is not selected for the Profile."""
        allowed = self._allowed_paths()
        requests: list[dict[str, Any]] = []
        seen: set[Path] = set()
        request_id = int(first_request_id)
        for item in skills:
            path = self._path(item.get("path"))
            if path is None or path in allowed or path in seen:
                continue
            seen.add(path)
            requests.append({
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "skills/config/write",
                "params": {"path": str(path), "enabled": False},
            })
            request_id += 1
        return requests

    def enable_selected_requests(
        self,
        skills: Iterable[Mapping[str, object]],
        *,
        first_request_id: int = 1,
    ) -> list[dict[str, Any]]:
        """Re-enable selected Skills after a prior Profile selection changed."""
        allowed = self._allowed_paths()
        requests: list[dict[str, Any]] = []
        seen: set[Path] = set()
        request_id = int(first_request_id)
        for item in skills:
            path = self._path(item.get("path"))
            if path is None or path not in allowed or item.get("enabled", True) is not False:
                continue
            if path in seen:
                continue
            seen.add(path)
            requests.append({
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "skills/config/write",
                "params": {"path": str(path), "enabled": True},
            })
            request_id += 1
        return requests

    def policy_requests(
        self,
        skills: Iterable[Mapping[str, object]],
        *,
        first_request_id: int = 1,
    ) -> list[dict[str, Any]]:
        """Build the startup writes that enforce the selected Skill set."""
        discovered = list(skills)
        disabled = self.disable_unselected_requests(
            discovered,
            first_request_id=first_request_id,
        )
        enabled = self.enable_selected_requests(
            discovered,
            first_request_id=first_request_id + len(disabled),
        )
        return disabled + enabled

    def refresh_request(self, request_id: int = 1) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": int(request_id),
            "method": "skills/list",
            "params": self.skills_list_params(),
        }

    def turn_skill_input(self, skill_id: str) -> dict[str, str]:
        """Return the only Skill input that this Profile may inject in a turn."""
        path = self.runtime.projected_skill_path(skill_id)
        manifest = self.runtime.selected_bindings()
        binding = manifest.get(str(skill_id or "").strip())
        if binding is None:
            raise AgentSkillProtocolError("Skill is not selected for this Profile")
        return {
            "type": "skill",
            "name": binding["name"],
            "path": str(path),
        }
