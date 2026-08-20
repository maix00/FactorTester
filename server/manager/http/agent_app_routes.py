"""Authenticated HTTP/SSE bridge for Manager-owned Profile Agents."""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import parse_qs

from server.manager.http.responses import json_response
from server.manager.services.agent_app_server import (
    AgentAppServerError,
    AgentAppServerSupervisor,
)


_SENSITIVE_EVENT_KEYS = frozenset({
    "api_key",
    "authorization",
    "cwd",
    "env",
    "home",
    "path",
    "secret",
    "token",
    "workspace",
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
})


def _public_value(value: object, key: str = "") -> object:
    """Remove server-local paths and credential-shaped fields from payloads."""
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
            after = int(query.get("after", ["0"])[0] or 0)
            self._stream_agent_events(supervisor, principal, identifier, after)
        except (AgentAppServerError, TypeError, ValueError) as exc:
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
        if not status.get("running"):
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
        deadline = time.monotonic() + 25.0
        try:
            while time.monotonic() < deadline:
                events = supervisor.events(
                    principal,
                    profile_id,
                    after=cursor,
                    timeout=min(5.0, max(0.1, deadline - time.monotonic())),
                )
                if not events:
                    self._write_sse_chunk(b": heartbeat\n\n")
                    continue
                for event in events:
                    sequence = int(event.get("sequence") or 0)
                    if sequence <= cursor:
                        continue
                    payload = json.dumps(
                        _public_value(event.get("payload") or {}),
                        ensure_ascii=False,
                    )
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
        except (AgentAppServerError, TypeError, ValueError) as exc:
            self._agent_app_error(exc)
            return True
