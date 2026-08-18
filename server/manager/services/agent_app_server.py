"""Manager-owned Codex app-server sessions for server Profiles."""

from __future__ import annotations

import threading
from typing import Any, Mapping

from server.manager.services.agent_app_server_errors import AgentAppServerError
from server.manager.services.agent_app_server_session import AgentAppServerSession
from server.manager.services.agent_profiles import AgentProfileService


class AgentAppServerSupervisor:
    """Keep at most one app-server process per claimed server Profile."""

    def __init__(
        self,
        profile_service: AgentProfileService,
        *,
        codex_binary: str = "codex",
    ) -> None:
        self.profile_service = profile_service
        self.codex_binary = str(codex_binary or "codex").strip() or "codex"
        self._sessions: dict[tuple[str, str], AgentAppServerSession] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _key(principal: str, profile_id: str) -> tuple[str, str]:
        owner = str(principal or "").strip()
        profile = str(profile_id or "").strip()
        if not owner or not profile:
            raise AgentAppServerError("principal and profile_id are required")
        return owner, profile

    def start(self, principal: str, profile_id: str) -> dict[str, Any]:
        key = self._key(principal, profile_id)
        with self._lock:
            existing = self._sessions.get(key)
            if existing is not None and existing.status().get("ready"):
                return existing.status()
            if existing is not None:
                existing.stop()
            context = self.profile_service.server_agent_context(*key)
            session = AgentAppServerSession(
                runtime=context["skill_runtime"],
                provider=context["provider"],
                codex_binary=self.codex_binary,
            )
            try:
                session.start()
            except Exception:
                session.stop()
                raise
            self._sessions[key] = session
            return session.status()

    def stop(self, principal: str, profile_id: str) -> dict[str, Any]:
        key = self._key(principal, profile_id)
        with self._lock:
            session = self._sessions.pop(key, None)
            if session is not None:
                session.stop()
            return {"stopped": True, "running": False}

    def status(self, principal: str, profile_id: str) -> dict[str, Any]:
        key = self._key(principal, profile_id)
        with self._lock:
            session = self._sessions.get(key)
            return session.status() if session is not None else {
                "ready": False,
                "running": False,
                "pid": None,
                "returncode": None,
                "event_sequence": 0,
                "stderr_tail": [],
            }

    def request(
        self,
        principal: str,
        profile_id: str,
        method: str,
        params: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        key = self._key(principal, profile_id)
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                raise AgentAppServerError("start the Profile Agent first")
        return session.request(method, params)

    def events(
        self,
        principal: str,
        profile_id: str,
        after: int = 0,
        timeout: float = 20.0,
    ) -> list[dict[str, Any]]:
        key = self._key(principal, profile_id)
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                raise AgentAppServerError("start the Profile Agent first")
        return session.wait_for_events(after, timeout)

    def stop_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.stop()


__all__ = ["AgentAppServerError", "AgentAppServerSupervisor"]
