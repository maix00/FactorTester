"""Ephemeral structured-document transport for page-scoped Profile Agents."""

from __future__ import annotations

import time
from copy import deepcopy
from threading import Condition, RLock
from urllib.parse import parse_qs

from server.manager.http.responses import json_response
from server.manager.services.assistance_drafts import AssistanceDraftError
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
    if (
        path == "$"
        and isinstance(value, dict)
        and value.get("document_kind") == "research_configuration"
    ):
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
        stale = [
            key
            for key, value in self._contexts.items()
            if float(value.get("updated_at") or 0) < threshold
        ]
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
        item = {
            "tab_id": tab_id,
            "assistance": deepcopy(assistance),
            "updated_at": time.time(),
        }
        with self._condition:
            self._prune()
            self._contexts[(principal, profile_id, tab_id)] = item
        return deepcopy(item)

    def current(self, principal: str, profile_id: str) -> dict | None:
        with self._condition:
            self._prune()
            values = [
                value
                for key, value in self._contexts.items()
                if key[:2] == (principal, profile_id)
            ]
            return (
                deepcopy(max(values, key=lambda item: item["updated_at"]))
                if values
                else None
            )

    def page(self, principal: str, profile_id: str, tab_id: str) -> dict | None:
        with self._condition:
            self._prune()
            return deepcopy(self._contexts.get((principal, profile_id, tab_id)))

    def validate(self, principal: str, profile_id: str, document: object) -> dict:
        page = self.current(principal, profile_id)
        if not page:
            raise ValueError("no assisted page is currently open")
        schema = page["assistance"].get("document_schema")
        if not isinstance(schema, dict):
            raise TypeError("assisted page did not publish a document schema")
        validate_document(schema, document)
        return page

    def validate_for_tab(
        self,
        principal: str,
        profile_id: str,
        tab_id: str,
        document: object,
    ) -> dict:
        page = self.page(principal, profile_id, tab_id)
        if not page:
            raise ValueError("page context is no longer active")
        schema = page["assistance"].get("document_schema")
        if not isinstance(schema, dict):
            raise TypeError("assisted page did not publish a document schema")
        validate_document(schema, document)
        return page

    def enqueue(self, principal: str, profile_id: str, value: dict) -> dict:
        tab_id = str(value.get("tab_id") or "").strip()
        expected_revision = value.get("expected_revision")
        document = value.get("document")
        key = (principal, profile_id, tab_id)
        with self._condition:
            self._prune()
            page = self._contexts.get(key)
            if not page:
                raise ValueError("page context is no longer active")
            revision = int(page["assistance"].get("revision") or 0)
            if not isinstance(expected_revision, int) or expected_revision != revision:
                raise ValueError(
                    f"page assistance revision conflict: expected {revision}"
                )
            validate_document(page["assistance"]["document_schema"], document)
            self._sequence += 1
            item = {
                "sequence": self._sequence,
                "kind": "replace_document",
                "expected_revision": revision,
                "document": deepcopy(document),
                "expires_at": time.time() + 15.0,
            }
            self._applications.setdefault(key, []).append(item)
            self._condition.notify_all()
            return deepcopy(item)

    def applications(
        self,
        principal: str,
        profile_id: str,
        tab_id: str,
        after: int,
        wait_seconds: float = 0.0,
    ) -> list[dict]:
        deadline = time.monotonic() + max(0.0, min(wait_seconds, 25.0))
        with self._condition:
            while True:
                self._prune()
                now = time.time()
                values = [
                    item
                    for item in self._applications.get(
                        (principal, profile_id, tab_id), []
                    )
                    if item["sequence"] > after
                    and float(item.get("expires_at") or now) >= now
                ]
                if values:
                    return deepcopy(values)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._condition.wait(remaining)

    def acknowledge(self, principal: str, profile_id: str, value: dict) -> dict:
        sequence = int(value.get("sequence") or 0)
        result = {
            "sequence": sequence,
            "success": value.get("success") is True,
            "revision": value.get("revision"),
            "error": str(value.get("error") or ""),
        }
        with self._condition:
            known = any(
                sequence == item["sequence"]
                for key, items in self._applications.items()
                if key[:2] == (principal, profile_id)
                for item in items
            )
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

_PAGE_ASSISTANCE_INSTRUCTION = """An active FactorTester page has published a
structured assistance document. First run `factortester assist inspect`; its
compact summary lists the current revision and queryable document sections.
Read only the document and schema subtrees needed for this request with
`factortester assist inspect --path <json-pointer>` (repeat `--path` in one
command when useful), rather than printing the complete page contract.
Container results are bounded and paginated; use a more specific pointer or
`--offset` and `--limit` instead of requesting a complete subtree. Build one
complete structured document. Retain it with
`factortester assist drafts create --stdin`, validate it with
`factortester assist drafts validate <draft-id>`, then apply it atomically with
`factortester assist drafts apply <draft-id>`.
Do not write candidate files into the Profile root or /tmp.
Do not inspect frontend source, tokens, or private HTTP APIs.
Do not manipulate the DOM or fill fields one at a time. If the revision
changed, inspect again and create a new draft."""


def page_assistance_turn_params(
    principal: str,
    profile_id: str,
    params: dict,
    *,
    store: PageAssistanceStore | None = None,
) -> dict:
    """Inject the built-in page protocol without requiring an optional Skill."""
    assistance_store = store or _STORE
    if assistance_store.current(principal, profile_id) is None:
        return dict(params)
    result = deepcopy(params)
    inputs = result.get("input")
    if not isinstance(inputs, list):
        return result
    result["input"] = [
        *inputs,
        {
            "type": "text",
            "text": _PAGE_ASSISTANCE_INSTRUCTION,
        },
    ]
    return result


class PageAssistanceRoutesMixin:
    def _get_page_assistance_routes(self, parsed) -> bool:
        if parsed.path not in {
            "/api/client/profile-agent/assistance",
            "/api/client/profile-agent/assistance/applications",
            "/api/client/profile-agent/assistance/drafts",
        }:
            return False
        query = parse_qs(parsed.query, keep_blank_values=True)
        try:
            principal, profile_id = self._agent_app_profile(
                query.get("profile_id", [""])[0]
            )
            if parsed.path.endswith("/drafts"):
                store = self._agent_service().assistance_drafts(principal, profile_id)
                draft_id = query.get("draft_id", [""])[0]
                value = store.get(draft_id) if draft_id else store.list()
                json_response(self, {"success": True, **value})
            elif parsed.path.endswith("/applications"):
                values = _STORE.applications(
                    principal,
                    profile_id,
                    query.get("tab_id", [""])[0],
                    int(query.get("after", ["0"])[0] or 0),
                    float(query.get("wait", ["0"])[0] or 0),
                )
                json_response(self, {"success": True, "applications": values})
            else:
                json_response(
                    self,
                    {
                        "success": True,
                        "profile_id": profile_id,
                        "page": _STORE.current(principal, profile_id),
                    },
                )
        except (AssistanceDraftError, TypeError, ValueError) as exc:
            self._agent_app_error(exc)
        return True

    def _post_page_assistance_routes(self, parsed) -> bool:
        if parsed.path not in {
            "/api/client/profile-agent/assistance/publish",
            "/api/client/profile-agent/assistance/validate",
            "/api/client/profile-agent/assistance/apply",
            "/api/client/profile-agent/assistance/acknowledge",
            "/api/client/profile-agent/assistance/drafts",
        }:
            return False
        try:
            payload = self._json_body(2 * 1024 * 1024)
            principal, profile_id = self._agent_app_profile(
                str(payload.get("profile_id") or "")
            )
            if parsed.path.endswith("/drafts"):
                page = _STORE.current(principal, profile_id)
                if not page:
                    raise ValueError("no assisted page is currently open")
                assistance = page["assistance"]
                document = payload.get("document")
                if not isinstance(document, dict):
                    raise ValueError("assistance document must be an object")
                item = (
                    self._agent_service()
                    .assistance_drafts(
                        principal,
                        profile_id,
                    )
                    .create(
                        principal=principal,
                        profile_id=profile_id,
                        tab_id=page["tab_id"],
                        page_kind=str(assistance.get("page_kind") or "page"),
                        page_revision=int(assistance.get("revision") or 0),
                        schema_version=int(assistance.get("schema_version") or 1),
                        document=document,
                        conversation_id=str(payload.get("conversation_id") or ""),
                        session_id=str(payload.get("session_id") or ""),
                    )
                )
                json_response(self, {"success": True, "draft": item}, 201)
            elif parsed.path.endswith("/publish"):
                item = _STORE.publish(principal, profile_id, payload)
                json_response(self, {"success": True, "page": item})
            elif parsed.path.endswith("/validate"):
                draft_id = str(payload.get("draft_id") or "")
                drafts = self._agent_service().assistance_drafts(principal, profile_id)
                draft = drafts.get(draft_id)
                try:
                    page = _STORE.validate_for_tab(
                        principal,
                        profile_id,
                        str(draft.get("tab_id") or ""),
                        draft.get("document"),
                    )
                except ValueError as exc:
                    drafts.set_status(draft_id, "rejected", error=str(exc))
                    raise
                drafts.set_status(draft_id, "validated")
                json_response(
                    self,
                    {
                        "success": True,
                        "valid": True,
                        "revision": page["assistance"]["revision"],
                    },
                )
            elif parsed.path.endswith("/acknowledge"):
                result = _STORE.acknowledge(principal, profile_id, payload)
                json_response(self, {"success": True, "result": result})
            else:
                draft_id = str(payload.get("draft_id") or "")
                drafts = self._agent_service().assistance_drafts(principal, profile_id)
                draft = drafts.get(draft_id)
                try:
                    item = _STORE.enqueue(
                        principal,
                        profile_id,
                        {
                            "tab_id": draft.get("tab_id"),
                            "expected_revision": draft.get("page_revision"),
                            "document": draft.get("document"),
                        },
                    )
                    result = _STORE.wait_result(item["sequence"])
                except ValueError as exc:
                    drafts.set_status(draft_id, "rejected", error=str(exc))
                    raise
                drafts.set_status(
                    draft_id,
                    "applied",
                    applied_revision=result.get("revision"),
                )
                json_response(self, {"success": True, "applied": result})
        except (AssistanceDraftError, TypeError, ValueError) as exc:
            self._agent_app_error(exc)
        return True

    def _delete_page_assistance_routes(self, parsed) -> bool:
        if parsed.path != "/api/client/profile-agent/assistance/drafts":
            return False
        try:
            payload = parse_qs(parsed.query, keep_blank_values=True)
            principal, profile_id = self._agent_app_profile(
                payload.get("profile_id", [""])[0],
            )
            deleted = (
                self._agent_service()
                .assistance_drafts(
                    principal,
                    profile_id,
                )
                .delete(payload.get("draft_id", [""])[0])
            )
            json_response(self, {"success": True, "deleted": deleted})
        except (AssistanceDraftError, TypeError, ValueError) as exc:
            self._agent_app_error(exc)
        return True
