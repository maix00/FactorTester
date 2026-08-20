"""Manager-owned Codex app-server sessions for server Profiles."""

from __future__ import annotations

import threading
from typing import Any, Callable, Mapping

from server.manager.services.agent_app_server_errors import AgentAppServerError
from server.manager.services.agent_app_server_session import AgentAppServerSession
from server.manager.services.agent_conversation_history import thread_messages
from server.manager.services.agent_profiles import AgentProfileService
from server.manager.services.agent_provider_network import (
    AgentProviderProxyUnavailable,
    resolve_provider_proxy,
)


class AgentAppServerSupervisor:
    """Keep at most one app-server process per claimed server Profile."""

    def __init__(
        self,
        profile_service: AgentProfileService,
        *,
        codex_binary: str = "codex",
        cc_switch_binary: str = "cc-switch",
        proxy_url_provider: Callable[[], str] | None = None,
        heartbeat_interval: float = 30.0,
    ) -> None:
        self.profile_service = profile_service
        self.codex_binary = str(codex_binary or "codex").strip() or "codex"
        self.cc_switch_binary = (
            str(cc_switch_binary or "cc-switch").strip() or "cc-switch"
        )
        self.proxy_url_provider = proxy_url_provider
        self.heartbeat_interval = max(0.1, float(heartbeat_interval))
        self._sessions: dict[tuple[str, str], AgentAppServerSession] = {}
        self._agent_session_tokens: dict[tuple[str, str], str] = {}
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
                self.profile_service.revoke_agent_session(
                    self._agent_session_tokens.pop(key, ""),
                )
                self.profile_service.pause_server_agent(*key)
            context = self.profile_service.server_agent_context(*key)
            claim = context["claim"]
            self.profile_service.heartbeat(
                key[0],
                str(claim["claim_id"]),
                str(claim["agent_id"]),
            )
            try:
                proxy_url = resolve_provider_proxy(
                    context["provider"],
                    self.proxy_url_provider,
                )
            except AgentProviderProxyUnavailable as exc:
                raise AgentAppServerError(str(exc), code=exc.code) from exc
            session = AgentAppServerSession(
                runtime=context["skill_runtime"],
                provider=context["provider"],
                factor_tester_auth=context.get("factor_tester_auth") or None,
                codex_binary=self.codex_binary,
                cc_switch_binary=self.cc_switch_binary,
                proxy_url=proxy_url,
            )
            try:
                session.start()
            except Exception:
                session.stop()
                auth = context.get("factor_tester_auth") or {}
                self.profile_service.revoke_agent_session(
                    str(auth.get("token") or ""),
                )
                raise
            self._sessions[key] = session
            auth = context.get("factor_tester_auth") or {}
            self._agent_session_tokens[key] = str(auth.get("token") or "")
            self._start_heartbeat(key, claim)
            return session.status()

    def stop(self, principal: str, profile_id: str) -> dict[str, Any]:
        key = self._key(principal, profile_id)
        with self._lock:
            session = self._sessions.pop(key, None)
            self._stop_heartbeat(key)
        if session is not None:
            session.stop()
        self.profile_service.revoke_agent_session(
            self._agent_session_tokens.pop(key, ""),
        )
        self.profile_service.pause_server_agent(*key)
        return {"stopped": True, "running": False}

    def status(self, principal: str, profile_id: str) -> dict[str, Any]:
        key = self._key(principal, profile_id)
        with self._lock:
            session = self._sessions.get(key)
            status = session.status() if session is not None else {
                "ready": False,
                "running": False,
                "pid": None,
                "returncode": None,
                "event_sequence": 0,
                "stderr_tail": [],
            }
        active = self.profile_service.conversation_store.active(*key)
        status["active_conversation_id"] = (
            active.get("conversation_id") if active else ""
        )
        return status

    def refresh_conversation_history(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
    ) -> bool:
        """Refresh one local Provider thread before a read-only export.

        The Manager owning the Agent is the only process allowed to resume the
        Provider thread.  A requesting peer never receives the Provider
        binding or credentials; it only receives the refreshed SQLite
        projection through the federation catalog endpoint.
        """
        key = self._key(principal, profile_id)
        identifier = str(conversation_id or "").strip()
        if not identifier:
            raise AgentAppServerError("conversation_id is required")
        conversation = self.profile_service.conversation(
            key[0], key[1], identifier,
        )
        if conversation is None:
            raise AgentAppServerError("conversation not found")
        thread_id = str(conversation.get("provider_thread_id") or "").strip()
        if not thread_id:
            return False
        with self._lock:
            session = self._sessions.get(key)
            if session is None or not session.status().get("running"):
                return False
        self.request(
            key[0],
            key[1],
            "thread/resume",
            {"threadId": thread_id},
            conversation_id=identifier,
        )
        return True

    def request(
        self,
        principal: str,
        profile_id: str,
        method: str,
        params: Mapping[str, object] | None = None,
        *,
        conversation_id: str = "",
    ) -> dict[str, Any]:
        key = self._key(principal, profile_id)
        identifier = str(conversation_id or "").strip()
        if method == "thread/list":
            raise AgentAppServerError(
                "thread/list is managed by the Profile conversation catalog"
            )
        conversation = None
        if identifier:
            conversation = self.profile_service.conversation(
                key[0], key[1], identifier,
            )
            if conversation is None:
                raise AgentAppServerError("conversation not found")
            self._validate_conversation_request(
                method,
                params or {},
                conversation,
                provider_id=self.profile_service.provider_id_for_profile(*key),
            )
        elif method in {
            "thread/read",
            "thread/start",
            "thread/resume",
            "turn/start",
            "turn/interrupt",
            "turn/steer",
        }:
            raise AgentAppServerError(
                "conversation_id is required for Profile Agent thread operations"
            )
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                raise AgentAppServerError("start the Profile Agent first")
        response = session.request(method, params)
        self._save_conversation_state(
            key,
            method,
            params or {},
            response,
            conversation,
        )
        return response

    @staticmethod
    def _thread_from_response(response: Mapping[str, object]) -> Mapping[str, object] | None:
        value: object = response
        for key in ("result", "response"):
            if isinstance(value, Mapping) and isinstance(value.get(key), Mapping):
                value = value[key]
        if not isinstance(value, Mapping):
            return None
        thread = value.get("thread")
        return thread if isinstance(thread, Mapping) else None

    @staticmethod
    def _thread_value(thread: Mapping[str, object], *keys: str) -> object:
        for key in keys:
            if key in thread and thread[key] not in (None, ""):
                return thread[key]
        return ""

    @classmethod
    def _validate_conversation_request(
        cls,
        method: str,
        params: Mapping[str, object],
        conversation: Mapping[str, object],
        *,
        provider_id: str = "",
    ) -> None:
        if method in {
            "thread/resume",
            "thread/read",
            "turn/start",
            "turn/interrupt",
            "turn/steer",
        }:
            stored_provider = str(conversation.get("provider_id") or "").strip()
            current_provider = str(provider_id or "").strip()
            if stored_provider and current_provider and stored_provider != current_provider:
                raise AgentAppServerError(
                    "conversation belongs to another Agent provider"
                )
        if method in {
            "thread/resume",
            "thread/read",
            "turn/start",
            "turn/interrupt",
            "turn/steer",
        }:
            expected = str(conversation.get("provider_thread_id") or "").strip()
            requested = str(
                params.get("threadId")
                or params.get("thread_id")
                or "",
            ).strip()
            if not expected or requested != expected:
                raise AgentAppServerError("conversation thread binding is invalid")
        if method == "thread/start" and conversation.get("provider_thread_id"):
            raise AgentAppServerError("conversation already has a thread; resume it")

    def _save_conversation_state(
        self,
        key: tuple[str, str],
        method: str,
        params: Mapping[str, object],
        response: Mapping[str, object],
        conversation: Mapping[str, object] | None,
    ) -> None:
        if conversation is None:
            return
        thread = self._thread_from_response(response)
        if method in {"thread/start", "thread/resume", "thread/read"} and thread is not None:
            thread_id = str(self._thread_value(thread, "id", "threadId", "thread_id") or "").strip()
            if not thread_id:
                raise AgentAppServerError("Agent did not return a conversation thread")
            created_at = self._thread_value(thread, "createdAt", "created_at")
            title = str(self._thread_value(thread, "name", "title") or "").strip()
            self.profile_service.conversation_store.save_thread(
                key[0],
                key[1],
                str(conversation["conversation_id"]),
                thread_id,
                provider_id=self.profile_service.provider_id_for_profile(*key),
                title=title,
                created_at=float(created_at) if created_at not in (None, "") else None,
            )
            self._persist_thread_history(key, str(conversation["conversation_id"]), thread)
            return
        if method == "turn/start":
            preview = self._preview(params)
            self.profile_service.conversation_store.touch(
                key[0],
                key[1],
                str(conversation["conversation_id"]),
                preview=preview,
            )

    @staticmethod
    def _preview(params: Mapping[str, object]) -> str:
        raw = params.get("prompt") or params.get("input") or ""
        if isinstance(raw, list):
            raw = " ".join(
                str(item.get("text") or "")
                for item in raw
                if isinstance(item, Mapping)
            )
        return " ".join(str(raw).split())[:2000]

    def _persist_thread_history(
        self,
        key: tuple[str, str],
        conversation_id: str,
        thread: Mapping[str, object],
    ) -> None:
        """Mirror textual Provider history without exposing tool internals."""
        store = self.profile_service.conversation_store
        try:
            store.replace_items(
                key[0], key[1], conversation_id, thread_messages(thread),
            )
        except (TypeError, ValueError, OSError):
            # A malformed Provider thread must not make an otherwise valid
            # resume fail.  The next resume can retry the projection refresh.
            return

    def delete_conversation(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
    ) -> bool:
        key = self._key(principal, profile_id)
        conversation = self.profile_service.conversation(*key, conversation_id)
        if conversation is None:
            return False
        thread_id = str(conversation.get("provider_thread_id") or "").strip()
        with self._lock:
            session = self._sessions.get(key)
        if session is not None and thread_id:
            try:
                session.delete_thread(thread_id)
            except AgentAppServerError:
                # The local catalog is authoritative for discoverability.  A
                # stopped or older provider process may not support deletion;
                # it must not make a user's local conversation undeletable.
                pass
        return self.profile_service.delete_conversation(*key, conversation_id)

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
                if session is None:
                    return
                if not session.status().get("running"):
                    # A crashed app-server must stop renewing its claim so the
                    # normal lease expiry can make the Profile reclaimable.  It
                    # must also lose its CLI capability immediately rather
                    # than waiting for a later manual lifecycle action.
                    self.stop(*key)
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

__all__ = ["AgentAppServerError", "AgentAppServerSupervisor"]
