"""Ephemeral page context and registered-action transport for Profile Agents."""

from __future__ import annotations

from copy import deepcopy
from threading import RLock
import time
from urllib.parse import parse_qs

from server.manager.http.responses import json_response


class PageAssistanceStore:
    """Keep short-lived browser context out of durable research storage."""

    def __init__(self, *, ttl_seconds: float = 900.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = RLock()
        self._contexts: dict[tuple[str, str, str], dict] = {}
        self._actions: dict[tuple[str, str, str], list[dict]] = {}
        self._sequence = 0

    def _prune(self) -> None:
        threshold = time.time() - self.ttl_seconds
        stale = [key for key, value in self._contexts.items()
                 if float(value.get("updated_at") or 0) < threshold]
        for key in stale:
            self._contexts.pop(key, None)
            self._actions.pop(key, None)

    def publish(self, principal: str, profile_id: str, value: dict) -> dict:
        tab_id = str(value.get("tab_id") or "").strip()
        context = value.get("context")
        if not tab_id or not isinstance(context, dict):
            raise ValueError("tab_id and context are required")
        if int(context.get("schema_version") or 0) != 1:
            raise ValueError("unsupported page context schema")
        item = {"tab_id": tab_id, "context": deepcopy(context), "updated_at": time.time()}
        with self._lock:
            self._prune()
            self._contexts[(principal, profile_id, tab_id)] = item
        return deepcopy(item)

    def current(self, principal: str, profile_id: str) -> dict | None:
        with self._lock:
            self._prune()
            values = [value for key, value in self._contexts.items()
                      if key[:2] == (principal, profile_id)]
            return deepcopy(max(values, key=lambda item: item["updated_at"])) if values else None

    def enqueue(self, principal: str, profile_id: str, value: dict) -> dict:
        tab_id = str(value.get("tab_id") or "").strip()
        section_id = str(value.get("section_id") or "").strip()
        action = value.get("action")
        if not tab_id or not section_id or not isinstance(action, dict):
            raise ValueError("tab_id, section_id and action are required")
        key = (principal, profile_id, tab_id)
        with self._lock:
            self._prune()
            if key not in self._contexts:
                raise ValueError("page context is no longer active")
            self._sequence += 1
            item = {"sequence": self._sequence, "section_id": section_id,
                    "action": deepcopy(action)}
            self._actions.setdefault(key, []).append(item)
            return deepcopy(item)

    def actions(self, principal: str, profile_id: str, tab_id: str, after: int) -> list[dict]:
        with self._lock:
            self._prune()
            return deepcopy([item for item in self._actions.get(
                (principal, profile_id, tab_id), []) if item["sequence"] > after])


_STORE = PageAssistanceStore()


class PageAssistanceRoutesMixin:
    def _get_page_assistance_routes(self, parsed) -> bool:
        if parsed.path not in {
            "/api/client/profile-agent/page-context",
            "/api/client/profile-agent/page-actions",
        }:
            return False
        query = parse_qs(parsed.query, keep_blank_values=True)
        try:
            principal, profile_id = self._agent_app_profile(
                query.get("profile_id", [""])[0]
            )
            if parsed.path.endswith("/page-actions"):
                actions = _STORE.actions(
                    principal, profile_id,
                    query.get("tab_id", [""])[0],
                    int(query.get("after", ["0"])[0] or 0),
                )
                json_response(self, {"success": True, "actions": actions})
            else:
                json_response(self, {
                    "success": True,
                    "profile_id": profile_id,
                    "page": _STORE.current(principal, profile_id),
                })
        except (TypeError, ValueError) as exc:
            self._agent_app_error(exc)
        return True

    def _post_page_assistance_routes(self, parsed) -> bool:
        if parsed.path not in {
            "/api/client/profile-agent/page-context",
            "/api/client/profile-agent/page-actions",
        }:
            return False
        try:
            payload = self._json_body(256 * 1024)
            principal, profile_id = self._agent_app_profile(
                str(payload.get("profile_id") or "")
            )
            if parsed.path.endswith("/page-actions"):
                item = _STORE.enqueue(principal, profile_id, payload)
                json_response(self, {"success": True, "queued": item})
            else:
                item = _STORE.publish(principal, profile_id, payload)
                json_response(self, {"success": True, "page": item})
        except (TypeError, ValueError) as exc:
            self._agent_app_error(exc)
        return True
