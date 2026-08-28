"""Manager-owned Codex app-server sessions for server Profiles."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from server.manager.services.agent_app_server_errors import AgentAppServerError
from server.manager.services.agent_app_server_session import AgentAppServerSession
from server.manager.services.agent_conversation_runtime import (
    AgentConversationRuntimeObserver,
)
from server.manager.services.agent_live_turn_chatkit import (
    active_turn_items,
    merge_active_turn,
)
from server.manager.services.agent_model_catalog import (
    build_model_catalog,
    validate_model_settings,
)
from server.manager.services.agent_profiles import AgentProfileService
from server.manager.services.agent_provider_network import (
    AgentProviderProxyUnavailable,
    resolve_provider_proxy,
)
from server.manager.services.agent_provider_thread_reader import (
    AgentProviderThreadReader,
)
from server.manager.services.provider_thread_chatkit import provider_thread_page


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
        self._model_catalog_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
        self._processing_turns: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.RLock()
        self.thread_reader = AgentProviderThreadReader(
            profile_service,
            codex_binary=self.codex_binary,
            cc_switch_binary=self.cc_switch_binary,
            proxy_url_provider=self.proxy_url_provider,
        )

    @staticmethod
    def _key(principal: str, profile_id: str) -> tuple[str, str]:
        owner = str(principal or "").strip()
        profile = str(profile_id or "").strip()
        if not owner or not profile:
            raise AgentAppServerError("principal and profile_id are required")
        return owner, profile

    def start(self, principal: str, profile_id: str) -> dict[str, Any]:
        key = self._key(principal, profile_id)
        self._model_catalog_cache.pop(key, None)
        # A lifecycle Agent and a history-only app-server must never share one
        # Profile state directory concurrently.
        self.thread_reader.close(*key)
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
            runtime_observer = AgentConversationRuntimeObserver(
                self.profile_service.conversation_store,
                key[0],
                key[1],
            )
            session = AgentAppServerSession(
                runtime=context["skill_runtime"],
                provider=context["provider"],
                factor_tester_auth=context.get("factor_tester_auth") or None,
                codex_binary=self.codex_binary,
                cc_switch_binary=self.cc_switch_binary,
                proxy_url=proxy_url,
                event_observer=lambda payload: self._observe_runtime_event(
                    key, runtime_observer, payload,
                ),
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
        self._model_catalog_cache.pop(key, None)
        with self._lock:
            session = self._sessions.pop(key, None)
            self._processing_turns.pop(key, None)
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
        processing = self._processing_turns.get(key) or {}
        status["processing_conversation_id"] = str(
            processing.get("conversation_id") or ""
        )
        return status

    def _observe_runtime_event(
        self,
        key: tuple[str, str],
        observer: AgentConversationRuntimeObserver,
        payload: Mapping[str, Any],
    ) -> None:
        observer.observe(payload)
        method = str(payload.get("method") or payload.get("type") or "")
        params = payload.get("params")
        params = params if isinstance(params, Mapping) else {}
        item = params.get("item")
        item = item if isinstance(item, Mapping) else {}
        item_type = str(item.get("type") or "").replace("_", "").casefold()
        final_assistant = method == "item/completed" and item_type in {
            "agentmessage", "assistantmessage",
        }
        failed_turn = (
            method.startswith("turn/")
            and method.rsplit("/", 1)[-1] in {
                "failed", "error", "aborted", "interrupted",
            }
        )
        if method == "app_server_exit" or failed_turn or final_assistant:
            with self._lock:
                self._processing_turns.pop(key, None)

    def refresh_conversation_history(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
    ) -> bool:
        """Compatibility probe for callers that previously refreshed SQLite."""
        self.conversation_items(principal, profile_id, conversation_id)
        return True

    @staticmethod
    def _response_result(response: Mapping[str, object]) -> Mapping[str, object]:
        value: object = response
        for key in ("result", "response"):
            if isinstance(value, Mapping) and isinstance(value.get(key), Mapping):
                value = value[key]
        return value if isinstance(value, Mapping) else {}

    def model_capabilities(
        self,
        principal: str,
        profile_id: str,
        *,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """Merge the Provider account catalog with Codex runtime capabilities."""
        key = self._key(principal, profile_id)
        now = time.monotonic()
        cached = self._model_catalog_cache.get(key)
        if not refresh and cached is not None and now - cached[0] < 60:
            return dict(cached[1])
        health = self.profile_service.profile_provider_health(*key)
        with self._lock:
            session = self._sessions.get(key)
        runtime_models: list[Mapping[str, object]] = []
        if session is not None and session.status().get("running"):
            response = session.request("model/list", {
                "includeHidden": False,
                "limit": 2000,
            })
            result = self._response_result(response)
            runtime_models = [
                item for item in (result.get("data") or [])
                if isinstance(item, Mapping)
            ]
        value = build_model_catalog(health, runtime_models)
        self._model_catalog_cache[key] = (now, value)
        return dict(value)

    def update_conversation_runtime_settings(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
        *,
        model_id: str,
        reasoning_effort: str,
        service_tier: str,
        refresh_catalog: bool = False,
    ) -> dict[str, Any]:
        catalog = self.model_capabilities(
            principal,
            profile_id,
            refresh=refresh_catalog,
        )
        model, effort, tier = validate_model_settings(
            catalog,
            model_id=model_id,
            reasoning_effort=reasoning_effort,
            service_tier=service_tier,
        )
        return self.profile_service.update_conversation_runtime_settings(
            principal,
            profile_id,
            conversation_id,
            model_id=model,
            reasoning_effort=effort,
            service_tier=tier,
        )

    def conversation_items(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
        *,
        limit: int = 10,
        after: str = "",
        view: str = "timeline",
        order: str = "desc",
    ) -> dict[str, Any]:
        """Read one ChatKit page from the authoritative local Provider thread."""
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
            if conversation.get("title") or conversation.get("preview"):
                raise AgentAppServerError(
                    "conversation Provider thread binding is missing"
                )
            return {
                "items": [], "has_more": False, "after": None,
                "turn_count": 0, "view": view, "order": order,
            }
        with self._lock:
            session = self._sessions.get(key)
            running = session is not None and session.status().get("running")
        if running:
            response = self.request(
                key[0], key[1], "thread/read", {
                    "threadId": thread_id,
                    "includeTurns": True,
                },
                conversation_id=identifier,
            )
            thread = self._thread_from_response(response)
        else:
            thread = self.thread_reader.read(
                key[0], key[1], thread_id,
                str(conversation.get("provider_id") or ""),
            )
        if not isinstance(thread, Mapping):
            raise AgentAppServerError("Provider did not return the conversation thread")
        page = provider_thread_page(
            thread, identifier, limit=limit, after=after, view=view, order=order,
        )
        processing = self._processing_turns.get(key) or {}
        if (
            running
            and not after
            and str(processing.get("conversation_id") or "") == identifier
            and session is not None
        ):
            page = merge_active_turn(
                page,
                active_turn_items(
                    session.events(int(processing.get("event_after") or 0)),
                    identifier,
                    thread_id,
                ),
            )
        return page

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
            running = session is not None and session.status().get("running")
        if not running:
            self.start(*key)
            with self._lock:
                session = self._sessions.get(key)
        if session is None:
            raise AgentAppServerError("Profile Agent could not be started")
        request_params = dict(params or {})
        if method == "turn/start" and conversation is not None:
            # The Manager-owned conversation is the settings authority.  A
            # browser cannot mutate a Provider default or smuggle a different
            # model choice directly into one turn.
            for field in ("model", "effort", "serviceTier"):
                request_params.pop(field, None)
            settings = {
                "model": conversation.get("model_id"),
                "effort": conversation.get("reasoning_effort"),
                "serviceTier": conversation.get("service_tier"),
            }
            request_params.update({
                name: str(value)
                for name, value in settings.items()
                if str(value or "").strip()
            })
        if method == "turn/start" and conversation is not None:
            event_after = int(session.status().get("event_sequence") or 0)
            with self._lock:
                self._processing_turns[key] = {
                    "conversation_id": str(conversation["conversation_id"]),
                    "event_after": event_after,
                }
        try:
            try:
                response = session.request(method, request_params)
            except AgentAppServerError as exc:
                # A process may exit between the running-state probe above and
                # AgentAppServerSession's pre-send readiness check. No request
                # was written in this exact failure mode, so one retry cannot
                # duplicate a turn.
                if str(exc) != "Profile Agent is not running":
                    raise
                self.start(*key)
                with self._lock:
                    session = self._sessions.get(key)
                if session is None:
                    raise AgentAppServerError(
                        "Profile Agent could not be started"
                    ) from exc
                response = session.request(method, request_params)
        except Exception:
            if method == "turn/start":
                with self._lock:
                    self._processing_turns.pop(key, None)
            raise
        self._save_conversation_state(
            key,
            method,
            request_params,
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
        self.thread_reader.close_all()

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
