"""Short-lived, read-only Provider app-server sessions for thread history."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Mapping

from server.manager.services.agent_app_server_errors import AgentAppServerError
from server.manager.services.agent_app_server_session import AgentAppServerSession


class AgentProviderThreadReader:
    """Read persisted threads without changing the Agent lifecycle state."""

    def __init__(
        self,
        profile_service: object,
        *,
        codex_binary: str,
        cc_switch_binary: str,
        proxy_url_provider: Callable[[], str] | None = None,
        idle_seconds: float = 180.0,
    ) -> None:
        self.profile_service = profile_service
        self.codex_binary = codex_binary
        self.cc_switch_binary = cc_switch_binary
        self.proxy_url_provider = proxy_url_provider
        self.idle_seconds = max(10.0, float(idle_seconds))
        self._sessions: dict[
            tuple[str, str], tuple[AgentAppServerSession, float]
        ] = {}
        self._lock = threading.RLock()

    def _close_locked(self, key: tuple[str, str]) -> None:
        value = self._sessions.pop(key, None)
        if value is None:
            return
        session, _ = value
        session.stop()

    def close(self, principal: str, profile_id: str) -> None:
        with self._lock:
            self._close_locked((str(principal), str(profile_id)))

    def _prune_locked(self, now: float) -> None:
        for key, (_, last_used) in list(self._sessions.items()):
            if now - last_used >= self.idle_seconds:
                self._close_locked(key)

    def _session(
        self,
        principal: str,
        profile_id: str,
        provider_id: str,
    ) -> AgentAppServerSession:
        key = (str(principal), str(profile_id))
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            cached = self._sessions.get(key)
            if cached is not None and cached[0].status().get("running"):
                self._sessions[key] = (cached[0], now)
                return cached[0]
            self._close_locked(key)
            context = self.profile_service.server_thread_read_context(
                *key, provider_id,
            )
            session = AgentAppServerSession(
                runtime=context["skill_runtime"],
                provider=context["provider"],
                factor_tester_auth=None,
                codex_binary=self.codex_binary,
                cc_switch_binary=self.cc_switch_binary,
                proxy_url="",
                read_only=True,
            )
            try:
                session.start()
            except Exception:
                session.stop()
                raise
            self._sessions[key] = (session, now)
            return session

    def read(
        self,
        principal: str,
        profile_id: str,
        thread_id: str,
        provider_id: str = "",
    ) -> Mapping[str, object]:
        identifier = str(thread_id or "").strip()
        if not identifier:
            raise AgentAppServerError("provider thread is unavailable")
        response = self._session(principal, profile_id, provider_id).request(
            "thread/read", {"threadId": identifier, "includeTurns": True},
        )
        value: object = response
        for key in ("result", "response"):
            if isinstance(value, Mapping) and isinstance(value.get(key), Mapping):
                value = value[key]
        thread = value.get("thread") if isinstance(value, Mapping) else None
        if not isinstance(thread, Mapping):
            raise AgentAppServerError("Provider did not return the conversation thread")
        return thread

    def history_workspace(self, principal, profile_id, provider_id=""):
        return self._session(principal, profile_id, provider_id).runtime.workspace_root

    def close_all(self) -> None:
        with self._lock:
            for key in list(self._sessions):
                self._close_locked(key)


__all__ = ["AgentProviderThreadReader"]
