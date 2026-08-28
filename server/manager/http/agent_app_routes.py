"""Authenticated HTTP/SSE bridge for Manager-owned Profile Agents."""

from __future__ import annotations

import json
from urllib.parse import parse_qs

from server.manager.http.page_assistance_routes import (
    page_assistance_turn_params,
)
from server.manager.http.responses import json_response
from server.manager.services.agent_app_server import (
    AgentAppServerError,
    AgentAppServerSupervisor,
)
from server.manager.services.provider_thread_chatkit import provider_item
from server.manager.storage.profile_runtime_store import ProfileRuntimeError

_SENSITIVE_EVENT_KEYS = frozenset({
    "api_key",
    "authorization",
    "env",
    "secret",
    "token",
})

_PUBLIC_CONVERSATION_KEYS = frozenset({
    "conversation_id",
    "profile_id",
    "title",
    "preview",
    "created_at",
    "updated_at",
    "active",
    # The adapter needs this opaque binding to resume the provider thread;
    # it is never used as ChatKit's browser-visible thread id.
    "provider_thread_id",
    "model_id",
    "reasoning_effort",
    "service_tier",
    "actual_model",
    "model_context_window",
    "total_tokens",
    "last_tokens",
    "compaction_count",
})


def _public_value(value: object, key: str = "") -> object:
    """Remove credential-bearing fields while retaining research records."""
    if key.casefold() in _SENSITIVE_EVENT_KEYS:
        return None
    if isinstance(value, dict):
        return {
            str(name): _public_value(item, str(name))
            for name, item in value.items()
            if str(name).casefold() not in _SENSITIVE_EVENT_KEYS
        }
    if isinstance(value, list):
        return [_public_value(item) for item in value]
    return value


def _public_conversation(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {
        key: _public_value(value[key], key)
        for key in _PUBLIC_CONVERSATION_KEYS
        if key in value
    }


class AgentAppServerRoutesMixin:
    """Expose a narrow, authenticated Profile Agent transport."""

    def _write_sse_chunk(self, payload: bytes) -> None:
        """Write one HTTP/1.1 chunk without allowing response buffering."""
        self.wfile.write(f"{len(payload):X}\r\n".encode("ascii"))
        self.wfile.write(payload)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def _agent_app_server(self) -> AgentAppServerSupervisor:
        service = getattr(self.state, "agent_app_server", None)
        if not isinstance(service, AgentAppServerSupervisor):
            raise AgentAppServerError("Profile Agent supervisor is unavailable")
        return service

    def _agent_app_profile(self, profile_id: str) -> tuple[str, str]:
        session = self._agent_session()
        if session is None:
            raise AgentAppServerError("login required")
        principal = self._agent_principal(session)
        identifier = str(profile_id or "").strip()
        if not self._profile_exists(principal, identifier):
            raise AgentAppServerError("Profile does not belong to current account")
        self._agent_service().require_local_server_runtime(principal, identifier)
        return principal, identifier

    def _agent_app_error(self, exc: Exception) -> None:
        message = str(exc)
        lowered = message.casefold()
        if "not found" in lowered:
            status = 404
        else:
            status = 409 if "claim" in lowered or "running" in lowered else 400
        json_response(
            self,
            {
                "success": False,
                "error": message,
                "code": str(
                    getattr(exc, "code", "agent_runtime_error")
                    or "agent_runtime_error"
                ),
            },
            status,
        )

    def _get_agent_app_routes(self, parsed) -> bool:
        if parsed.path not in {
            "/api/client/profile-agent",
            "/api/client/profile-agent/events",
            "/api/client/profile-agent/conversations",
            "/api/client/profile-agent/models",
            "/api/client/profile-agent/conversation-items",
        }:
            return False
        query = parse_qs(parsed.query, keep_blank_values=True)
        profile_id = query.get("profile_id", [""])[0]
        try:
            principal, identifier = self._agent_app_profile(profile_id)
            supervisor = self._agent_app_server()
            if parsed.path == "/api/client/profile-agent":
                json_response(
                    self,
                    {
                        "success": True,
                        "profile_id": identifier,
                        "status": _public_value(supervisor.status(principal, identifier)),
                    },
                )
                return True
            if parsed.path.endswith("/conversations"):
                json_response(self, {
                    "success": True,
                    "profile_id": identifier,
                    "conversations": [
                        _public_conversation(item)
                        for item in supervisor.profile_service.conversations(
                            principal, identifier,
                        )
                    ],
                })
                return True
            if parsed.path.endswith("/models"):
                refresh = str(query.get("refresh", [""])[0]).casefold() in {
                    "1", "true", "yes",
                }
                json_response(self, {
                    "success": True,
                    "profile_id": identifier,
                    **supervisor.model_capabilities(
                        principal, identifier, refresh=refresh,
                    ),
                })
                return True
            if parsed.path.endswith("/conversation-items"):
                conversation_id = str(
                    query.get("conversation_id", [""])[0] or ""
                ).strip()
                limit = int(query.get("limit", ["10"])[0] or 10)
                after_cursor = str(query.get("after", [""])[0] or "")
                view = str(query.get("view", ["timeline"])[0] or "timeline")
                order = str(query.get("order", ["desc"])[0] or "desc")
                page = supervisor.conversation_items(
                    principal, identifier, conversation_id,
                    limit=limit,
                    after=after_cursor,
                    view=view,
                    order=order,
                )
                json_response(self, {
                    "success": True,
                    "profile_id": identifier,
                    "conversation_id": conversation_id,
                    **page,
                })
                return True
            after = int(query.get("after", ["0"])[0] or 0)
            self._stream_agent_events(supervisor, principal, identifier, after)
        except (AgentAppServerError, ProfileRuntimeError, TypeError, ValueError) as exc:
            self._agent_app_error(exc)
        return True

    def _stream_agent_events(
        self,
        supervisor: AgentAppServerSupervisor,
        principal: str,
        profile_id: str,
        after: int,
    ) -> None:
        status = supervisor.status(principal, profile_id)
        if (
            not status.get("running")
            and int(status.get("event_sequence") or 0) <= max(0, int(after))
        ):
            raise AgentAppServerError("start the Profile Agent before opening events")
        # BaseHTTPRequestHandler defaults to HTTP/1.0.  An SSE response has no
        # known Content-Length, so HTTP/1.0 keep-alive leaves browsers and
        # intermediaries free to buffer the body until the connection closes.
        # Use explicit HTTP/1.1 chunk framing for incremental delivery.
        self.protocol_version = "HTTP/1.1"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("Content-Encoding", "identity")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        cursor = max(0, int(after))
        conversation_id = str(
            status.get("active_conversation_id") or ""
        ).strip()
        try:
            while True:
                events = supervisor.events(
                    principal,
                    profile_id,
                    after=cursor,
                    timeout=5.0,
                )
                if not events:
                    if not supervisor.status(principal, profile_id).get("running"):
                        return
                    self._write_sse_chunk(b": heartbeat\n\n")
                    continue
                for event in events:
                    sequence = int(event.get("sequence") or 0)
                    if sequence <= cursor:
                        continue
                    public_payload = _public_value(event.get("payload") or {})
                    if isinstance(public_payload, dict) and conversation_id:
                        params = public_payload.get("params")
                        raw_item = params.get("item") if isinstance(params, dict) else None
                        if isinstance(raw_item, dict):
                            projected = provider_item(raw_item, conversation_id)
                            if projected is not None:
                                public_payload["chatkit_item"] = projected
                    payload = json.dumps(public_payload, ensure_ascii=False)
                    self._write_sse_chunk(
                        f"id: {sequence}\ndata: {payload}\n\n".encode("utf-8")
                    )
                    cursor = sequence
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _post_agent_app_routes(self, parsed) -> bool:
        if parsed.path not in {
            "/api/client/profile-agent/start",
            "/api/client/profile-agent/stop",
            "/api/client/profile-agent/rpc",
            "/api/client/profile-agent/conversations/create",
            "/api/client/profile-agent/conversations/select",
            "/api/client/profile-agent/conversations/update",
            "/api/client/profile-agent/conversations/settings",
            "/api/client/profile-agent/conversations/delete",
        }:
            return False
        try:
            payload = self._json_body(512 * 1024)
            profile_id = str(payload.get("profile_id") or "").strip()
            principal, identifier = self._agent_app_profile(profile_id)
            supervisor = self._agent_app_server()
            if parsed.path.endswith("/conversations/create"):
                value = supervisor.profile_service.create_conversation(
                    principal,
                    identifier,
                    title=str(payload.get("title") or "").strip(),
                )
                json_response(self, {
                    "success": True,
                    "conversation": _public_conversation(value),
                })
                return True
            conversation_id = str(payload.get("conversation_id") or "").strip()
            if parsed.path.endswith("/conversations/select"):
                value = supervisor.profile_service.select_conversation(
                    principal, identifier, conversation_id,
                )
                json_response(self, {
                    "success": True,
                    "conversation": _public_conversation(value),
                })
                return True
            if parsed.path.endswith("/conversations/update"):
                value = supervisor.profile_service.update_conversation(
                    principal,
                    identifier,
                    conversation_id,
                    title=payload.get("title"),
                    preview=payload.get("preview"),
                )
                json_response(self, {
                    "success": True,
                    "conversation": _public_conversation(value),
                })
                return True
            if parsed.path.endswith("/conversations/settings"):
                value = supervisor.update_conversation_runtime_settings(
                    principal,
                    identifier,
                    conversation_id,
                    model_id=str(payload.get("model_id") or "").strip(),
                    reasoning_effort=str(
                        payload.get("reasoning_effort") or ""
                    ).strip(),
                    service_tier=str(payload.get("service_tier") or "").strip(),
                    refresh_catalog=bool(payload.get("refresh_catalog")),
                )
                json_response(self, {
                    "success": True,
                    "conversation": _public_conversation(value),
                })
                return True
            if parsed.path.endswith("/conversations/delete"):
                deleted = supervisor.delete_conversation(
                    principal, identifier, conversation_id,
                )
                json_response(self, {"success": True, "deleted": deleted})
                return True
            if parsed.path.endswith("/start"):
                status = supervisor.start(principal, identifier)
                json_response(self, {
                    "success": True,
                    "profile_id": identifier,
                    "status": _public_value(status),
                })
                return True
            if parsed.path.endswith("/stop"):
                value = supervisor.stop(principal, identifier)
                json_response(self, {"success": True, **value})
                return True
            method = str(payload.get("method") or "").strip()
            params = payload.get("params") or {}
            if not isinstance(params, dict):
                raise AgentAppServerError("params must be an object")
            if method == "turn/start":
                params = page_assistance_turn_params(
                    principal, identifier, params,
                )
            response = supervisor.request(
                principal,
                identifier,
                method,
                params,
                conversation_id=str(payload.get("conversation_id") or "").strip(),
            )
            json_response(self, {
                "success": True,
                "response": _public_value(response),
            })
            return True
        except (AgentAppServerError, ProfileRuntimeError, TypeError, ValueError) as exc:
            self._agent_app_error(exc)
            return True
