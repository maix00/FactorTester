"""Manager-owned Codex app-server sessions for server Profiles."""

from __future__ import annotations

import threading
from typing import Any, Callable, Mapping

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
        proxy_url_provider: Callable[[], str] | None = None,
        heartbeat_interval: float = 30.0,
    ) -> None:
        self.profile_service = profile_service
        self.codex_binary = str(codex_binary or "codex").strip() or "codex"
        self.proxy_url_provider = proxy_url_provider
        self.heartbeat_interval = max(0.1, float(heartbeat_interval))
        self._sessions: dict[tuple[str, str], AgentAppServerSession] = {}
        self._heartbeat_controls: dict[tuple[str, str], threading.Event] = {}
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
            if existing is not None:
                existing_status = existing.status()
            else:
                existing_status = {}
            if existing is not None and existing_status.get("ready") and existing_status.get("running"):
                return existing.status()
            if existing is not None:
                self._sessions.pop(key, None)
                self._stop_heartbeat(key)
                existing.stop()
                self.profile_service.pause_server_agent(*key)
            context = self.profile_service.server_agent_context(*key)
            claim = context["claim"]
            self.profile_service.heartbeat(
                key[0],
                str(claim["claim_id"]),
                str(claim["agent_id"]),
            )
            session = AgentAppServerSession(
                runtime=context["skill_runtime"],
                provider=context["provider"],
                codex_binary=self.codex_binary,
                proxy_url=self._proxy_url(),
            )
            try:
                session.start()
            except Exception:
                session.stop()
                raise
            self._sessions[key] = session
            self._start_heartbeat(key, claim)
            return session.status()

    def stop(self, principal: str, profile_id: str) -> dict[str, Any]:
        key = self._key(principal, profile_id)
        with self._lock:
            session = self._sessions.pop(key, None)
            self._stop_heartbeat(key)
        if session is not None:
            session.stop()
        self.profile_service.pause_server_agent(*key)
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
            keys = list(self._sessions)
        for principal, profile_id in keys:
            self.stop(principal, profile_id)

    def _start_heartbeat(
        self,
        key: tuple[str, str],
        claim: Mapping[str, object],
    ) -> None:
        self._stop_heartbeat(key)
        stop_event = threading.Event()
        self._heartbeat_controls[key] = stop_event
        claim_id = str(claim.get("claim_id") or "")
        agent_id = str(claim.get("agent_id") or "")

        def run() -> None:
            while not stop_event.wait(self.heartbeat_interval):
                with self._lock:
                    session = self._sessions.get(key)
                if session is None or not session.status().get("running"):
                    # A crashed app-server must stop renewing its claim so the
                    # normal lease expiry can make the Profile reclaimable.
                    return
                try:
                    self.profile_service.heartbeat(
                        key[0], claim_id, agent_id,
                    )
                except Exception:
                    # A released or unavailable claim cannot be renewed.  The
                    # app-server remains isolated from the Manager's control
                    # path and will be stopped by the next lifecycle action.
                    return

        threading.Thread(
            target=run,
            name="factor-manager-agent-claim-heartbeat",
            daemon=True,
        ).start()

    def _stop_heartbeat(self, key: tuple[str, str]) -> None:
        stop_event = self._heartbeat_controls.pop(key, None)
        if stop_event is not None:
            stop_event.set()

    def _proxy_url(self) -> str:
        if self.proxy_url_provider is None:
            return ""
        try:
            return str(self.proxy_url_provider() or "").strip()
        except Exception:
            return ""


__all__ = ["AgentAppServerError", "AgentAppServerSupervisor"]
