"""Ephemeral structured-document transport for page-scoped Profile Agents."""

from __future__ import annotations

from copy import deepcopy
from threading import Condition, RLock
import time
from urllib.parse import parse_qs

from server.manager.http.responses import json_response
from server.services import research_configurations


def validate_document(schema: dict, value: object, path: str = "$") -> None:
    expected = schema.get("type")
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }
    if expected in valid and not valid[expected]:
        raise ValueError(f"{path} must be {expected}")
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} is not an allowed value")
    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        for key in schema.get("required") or []:
            if key not in value:
                raise ValueError(f"{path}.{key} is required")
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                raise ValueError(f"{path} has unsupported fields: {extra}")
        for key, child in properties.items():
            if key in value and isinstance(child, dict):
                validate_document(child, value[key], f"{path}.{key}")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            validate_document(schema["items"], item, f"{path}[{index}]")
    if path == "$" and isinstance(value, dict) \
            and value.get("document_kind") == "research_configuration":
        research_configurations.validate_payload(value.get("configuration"))


class PageAssistanceStore:
    def __init__(self, *, ttl_seconds: float = 900.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = RLock()
        self._condition = Condition(self._lock)
        self._contexts: dict[tuple[str, str, str], dict] = {}
        self._applications: dict[tuple[str, str, str], list[dict]] = {}
        self._sequence = 0
        self._results: dict[int, dict] = {}

    def _prune(self) -> None:
        threshold = time.time() - self.ttl_seconds
        stale = [key for key, value in self._contexts.items()
                 if float(value.get("updated_at") or 0) < threshold]
        for key in stale:
            self._contexts.pop(key, None)
            self._applications.pop(key, None)

    def publish(self, principal: str, profile_id: str, value: dict) -> dict:
        tab_id = str(value.get("tab_id") or "").strip()
        assistance = value.get("assistance")
        if not tab_id or not isinstance(assistance, dict):
            raise ValueError("tab_id and assistance are required")
        if int(assistance.get("schema_version") or 0) != 1:
            raise ValueError("unsupported page assistance schema")
        item = {"tab_id": tab_id, "assistance": deepcopy(assistance),
                "updated_at": time.time()}
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

    def validate(self, principal: str, profile_id: str, document: object) -> dict:
        page = self.current(principal, profile_id)
        if not page:
            raise ValueError("no assisted page is currently open")
        schema = page["assistance"].get("document_schema")
        if not isinstance(schema, dict):
            raise ValueError("assisted page did not publish a document schema")
        validate_document(schema, document)
        return page

    def enqueue(self, principal: str, profile_id: str, value: dict) -> dict:
        tab_id = str(value.get("tab_id") or "").strip()
        expected_revision = value.get("expected_revision")
        document = value.get("document")
        key = (principal, profile_id, tab_id)
        with self._lock:
            self._prune()
            page = self._contexts.get(key)
            if not page:
                raise ValueError("page context is no longer active")
            revision = int(page["assistance"].get("revision") or 0)
            if not isinstance(expected_revision, int) or expected_revision != revision:
                raise ValueError(f"page assistance revision conflict: expected {revision}")
            validate_document(page["assistance"]["document_schema"], document)
            self._sequence += 1
            item = {"sequence": self._sequence, "kind": "replace_document",
                    "expected_revision": revision, "document": deepcopy(document),
                    "expires_at": time.time() + 15.0}
            self._applications.setdefault(key, []).append(item)
            return deepcopy(item)

    def applications(self, principal: str, profile_id: str,
                     tab_id: str, after: int) -> list[dict]:
        with self._lock:
            self._prune()
            now = time.time()
            return deepcopy([item for item in self._applications.get(
                (principal, profile_id, tab_id), [])
                if item["sequence"] > after and float(item.get("expires_at") or now) >= now])

    def acknowledge(self, principal: str, profile_id: str, value: dict) -> dict:
        sequence = int(value.get("sequence") or 0)
        result = {"sequence": sequence, "success": value.get("success") is True,
                  "revision": value.get("revision"), "error": str(value.get("error") or "")}
        with self._condition:
            known = any(sequence == item["sequence"] for key, items in self._applications.items()
                        if key[:2] == (principal, profile_id) for item in items)
            if not known:
                raise ValueError("unknown assistance application")
            self._results[sequence] = result
            for key, items in list(self._applications.items()):
                retained = [item for item in items if item["sequence"] != sequence]
                if retained:
                    self._applications[key] = retained
                else:
                    self._applications.pop(key, None)
            self._condition.notify_all()
        return deepcopy(result)

    def wait_result(self, sequence: int, timeout: float = 10.0) -> dict:
        deadline = time.monotonic() + timeout
        with self._condition:
            while sequence not in self._results:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("assisted page did not apply the document in time")
                self._condition.wait(remaining)
            result = deepcopy(self._results.pop(sequence))
        if not result["success"]:
            raise ValueError(result["error"] or "assisted page rejected the document")
        return result


_STORE = PageAssistanceStore()


class PageAssistanceRoutesMixin:
    def _get_page_assistance_routes(self, parsed) -> bool:
        if parsed.path not in {
            "/api/client/profile-agent/assistance",
            "/api/client/profile-agent/assistance/applications",
        }:
            return False
        query = parse_qs(parsed.query, keep_blank_values=True)
        try:
            principal, profile_id = self._agent_app_profile(query.get("profile_id", [""])[0])
            if parsed.path.endswith("/applications"):
                values = _STORE.applications(
                    principal, profile_id, query.get("tab_id", [""])[0],
                    int(query.get("after", ["0"])[0] or 0),
                )
                json_response(self, {"success": True, "applications": values})
            else:
                json_response(self, {"success": True, "profile_id": profile_id,
                                     "page": _STORE.current(principal, profile_id)})
        except (TypeError, ValueError) as exc:
            self._agent_app_error(exc)
        return True

    def _post_page_assistance_routes(self, parsed) -> bool:
        if parsed.path not in {
            "/api/client/profile-agent/assistance/publish",
            "/api/client/profile-agent/assistance/validate",
            "/api/client/profile-agent/assistance/apply",
            "/api/client/profile-agent/assistance/acknowledge",
        }:
            return False
        try:
            payload = self._json_body(2 * 1024 * 1024)
            principal, profile_id = self._agent_app_profile(str(payload.get("profile_id") or ""))
            if parsed.path.endswith("/publish"):
                item = _STORE.publish(principal, profile_id, payload)
                json_response(self, {"success": True, "page": item})
            elif parsed.path.endswith("/validate"):
                page = _STORE.validate(principal, profile_id, payload.get("document"))
                json_response(self, {"success": True, "valid": True,
                                     "revision": page["assistance"]["revision"]})
            elif parsed.path.endswith("/acknowledge"):
                result = _STORE.acknowledge(principal, profile_id, payload)
                json_response(self, {"success": True, "result": result})
            else:
                item = _STORE.enqueue(principal, profile_id, payload)
                result = _STORE.wait_result(item["sequence"])
                json_response(self, {"success": True, "applied": result})
        except (TypeError, ValueError) as exc:
            self._agent_app_error(exc)
        return True
