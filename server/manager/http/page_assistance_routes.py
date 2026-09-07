"""Ephemeral structured-document transport for page-scoped Profile Agents."""

from __future__ import annotations

import re
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
    if isinstance(value, str):
        if len(value) < int(schema.get("minLength") or 0):
            raise ValueError(f"{path} is too short")
        pattern = schema.get("pattern")
        if pattern and re.fullmatch(str(pattern), value) is None:
            raise ValueError(f"{path} has an invalid format")
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and "minimum" in schema
        and value < schema["minimum"]
    ):
        raise ValueError(f"{path} is below its minimum")
    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        forbidden = sorted(
            str(key) for key in schema.get("x-forbidden-properties") or []
            if key in value
        )
        if forbidden:
            raise ValueError(f"{path} has read-only fields: {forbidden}")
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
    if isinstance(value, list):
        if len(value) < int(schema.get("minItems") or 0):
            raise ValueError(f"{path} has too few items")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise ValueError(f"{path} has too many items")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                validate_document(schema["items"], item, f"{path}[{index}]")
    if (
        path == "$"
        and isinstance(value, dict)
        and value.get("document_kind") == "research_configuration"
    ):
        research_configurations.validate_payload(value.get("configuration"))


def validate_navigation(value: object) -> None:
    if not isinstance(value, dict) or int(value.get("schema_version") or 0) != 1:
        raise ValueError("page assistance navigation schema is required")
    root_id = str(value.get("root_id") or "").strip()
    nodes = value.get("nodes")
    if not root_id or not isinstance(nodes, dict) or root_id not in nodes:
        raise ValueError("page assistance navigation root is invalid")
    if len(nodes) > 1000:
        raise ValueError("page assistance navigation has too many nodes")
    for node_id, node in nodes.items():
        if not isinstance(node, dict) or str(node.get("id") or "") != node_id:
            raise ValueError("page assistance navigation node is invalid")
        if not str(node.get("kind") or "").strip():
            raise ValueError("page assistance navigation node kind is required")
        children = node.get("children") or []
        if not isinstance(children, list) or any(
            str(child) not in nodes for child in children
        ):
            raise ValueError("page assistance navigation child is invalid")


class PageAssistanceStore:
    def __init__(self, *, ttl_seconds: float = 900.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = RLock()
        self._condition = Condition(self._lock)
        self._contexts: dict[tuple[str, str, str], dict] = {}
        self._applications: dict[tuple[str, str, str], list[dict]] = {}
        self._workspaces: dict[tuple[str, str], dict] = {}
        self._sequence = 0
        self._results: dict[int, dict] = {}

    def _prune(self) -> None:
        threshold = time.time() - self.ttl_seconds
        stale = [
            key
            for key, value in self._contexts.items()
            if float(value.get("updated_at") or 0) < threshold
        ]
        for key in list(self._workspaces):
            if self._workspaces[key].get("updated_at", 0) < threshold:
                self._workspaces.pop(key, None)
        for key in stale:
            self._contexts.pop(key, None)
            self._applications.pop(key, None)

    def publish_workspace(self, principal: str, profile_id: str, workspace: dict) -> None:
        tabs = workspace.get("tabs") or []
        if len(tabs) > 1000:
            raise ValueError("too many workspace tabs")
        tab_ids = {str(tab["tab_id"]) for tab in tabs}
        with self._condition:
            for key in list(self._contexts):
                if key[:2] == (principal, profile_id) and key[2] not in tab_ids:
                    self._contexts.pop(key, None)
                    self._applications.pop(key, None)
            for tab in tabs:
                if isinstance(tab.get("assistance"), dict):
                    self.publish(principal, profile_id, {
                        "tab_id": tab["tab_id"], "assistance": tab["assistance"],
                        "activate": tab["tab_id"] == workspace.get("active_tab_id"),
                    })
            previous = self._workspaces.get((principal, profile_id), {})
            self._workspaces[(principal, profile_id)] = {
                "updated_at": time.time() if any("assistance" in tab for tab in tabs)
                              else previous.get("updated_at", time.time()),
                "active_tab_id": workspace.get("active_tab_id") if workspace.get("active_tab_id") in tab_ids else None,
                "tabs": [{**{key: tab.get(key) for key in (
                    "tab_id", "title", "path", "kind", "research_id", "parent_tab_id")},
                    "writable": (bool(tab.get("assistance")) and not (tab["assistance"].get("document_schema") or {}).get("readOnly")) if "assistance" in tab else bool(tab.get("writable"))}
                    for tab in tabs],
            }

    def workspace(self, principal: str, profile_id: str) -> dict:
        with self._condition:
            self._prune()
            return deepcopy(self._workspaces.get((principal, profile_id), {}))

    def publish(self, principal: str, profile_id: str, value: dict) -> dict:
        tab_id = str(value.get("tab_id") or "").strip()
        assistance = value.get("assistance")
        if not tab_id or not isinstance(assistance, dict):
            raise ValueError("tab_id and assistance are required")
        if int(assistance.get("schema_version") or 0) != 1:
            raise ValueError("unsupported page assistance schema")
        validate_navigation(assistance.get("navigation"))
        item = {
            "tab_id": tab_id,
            "assistance": deepcopy(assistance),
            "updated_at": time.time(),
        }
        with self._condition:
            self._prune()
            previous = self._contexts.get((principal, profile_id, tab_id)) or {}
            item["activated_at"] = (
                item["updated_at"] if value.get("activate") is True
                else previous.get("activated_at", 0)
            )
            self._contexts[(principal, profile_id, tab_id)] = item
        return deepcopy(item)

    def current(self, principal: str, profile_id: str) -> dict | None:
        with self._condition:
            self._prune()
            workspace = self._workspaces.get((principal, profile_id))
            if workspace is not None:
                active = workspace.get("active_tab_id")
                return deepcopy(self._contexts.get((principal, profile_id, active)))
            values = [
                value
                for key, value in self._contexts.items()
                if key[:2] == (principal, profile_id)
            ]
            return (
                deepcopy(max(values, key=lambda item: (
                    bool(item.get("activated_at")),
                    item.get("activated_at") or item["updated_at"],
                )))
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

    def resolve_target(
        self,
        principal: str,
        profile_id: str,
        *,
        page_kind: str,
        schema_version: int,
        document: object,
        tab_id: str = "",
    ) -> dict:
        page = self.page(principal, profile_id, tab_id) if tab_id else self.current(principal, profile_id)
        expected_kind = str(page_kind or "").strip()
        if not page:
            raise ValueError(
                f"activate a compatible {expected_kind or 'assisted'} page"
            )
        assistance = page["assistance"]
        if str(assistance.get("page_kind") or "") != expected_kind:
            raise ValueError(f"activate a compatible {expected_kind} page")
        if int(assistance.get("schema_version") or 0) != int(schema_version):
            raise ValueError(
                f"activate a compatible {expected_kind} page with schema "
                f"version {schema_version}"
            )
        schema = assistance.get("document_schema")
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
            draft_id = str(value.get("draft_id") or "")
            if draft_id:
                for pending_key, items in list(self._applications.items()):
                    pending = next((
                        item for item in items
                        if str(item.get("draft_id") or "") == draft_id
                    ), None)
                    if pending is None:
                        continue
                    if pending_key == key:
                        return deepcopy(pending)
                    retained = [item for item in items if item is not pending]
                    if retained:
                        self._applications[pending_key] = retained
                    else:
                        self._applications.pop(pending_key, None)
                    self._results[pending["sequence"]] = {
                        "sequence": pending["sequence"],
                        "success": False,
                        "revision": None,
                        "error": "assistance draft retargeted to the active page",
                        "draft_id": draft_id,
                        "target_tab_id": str(pending.get("tab_id") or ""),
                        "target_revision": pending.get("expected_revision"),
                    }
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
                "tab_id": tab_id,
                "expected_revision": revision,
                "document": deepcopy(document),
                "draft_id": draft_id,
                "expires_at": time.time() + self.ttl_seconds,
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
                    for key, items in self._applications.items()
                    if key[:2] == (principal, profile_id) and (not tab_id or key[2] == tab_id)
                    for item in items
                    if item["sequence"] > after
                    and float(item.get("expires_at") or now) >= now
                ]
                if values:
                    return deepcopy(sorted(values, key=lambda item: item["sequence"]))
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
            application = next((
                item
                for key, items in self._applications.items()
                if key[:2] == (principal, profile_id)
                for item in items
                if sequence == item["sequence"]
            ), None)
            if application is None:
                raise ValueError("unknown assistance application")
            result["draft_id"] = str(application.get("draft_id") or "")
            result["target_tab_id"] = str(application.get("tab_id") or "")
            result["target_revision"] = application.get("expected_revision")
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
                    raise TimeoutError("assisted page application is still queued")
                self._condition.wait(remaining)
            result = deepcopy(self._results.pop(sequence))
        if not result["success"]:
            raise ValueError(result["error"] or "assisted page rejected the document")
        return result


_STORE = PageAssistanceStore()

_PAGE_ASSISTANCE_INSTRUCTION = """The FactorTester workspace exposes open tabs and research folder hierarchy via
`factortester assist inspect`. Its workspace.active_tab_id identifies the active
page. Self may access all published pages; other Profiles only their research
scope. Use `assist inspect --tab-id ID` and `assist drafts create --from-current
--tab-id ID` for a specific page. Drafts remain bound to that target even if the
user switches tabs. Background applications remain queued until the target page
loads and validates them; do not claim completion before an applied receipt.
Each page declares its own schema; pages without an assistance document are
read-only. Do not infer a writable schema from another page.
An active FactorTester page has published a
structured assistance document. First run `factortester assist inspect`; it
lists only the page's registered tabs (including mounted and unmounted tabs).
Read only the page-registered semantic node needed for this request with
`factortester assist inspect --node <node-id>`. Each page defines its own
navigation hierarchy: for example tabs, chips and fields for test pages,
sections for factor editors, or report chapters. Do not scan generic JSON
subtrees or enumerate candidate collections. Use the candidate lookup command
registered by a field when candidates are needed. Build one complete
structured document patch. Start from the page's complete document without
printing it by running `factortester assist drafts create --from-current`.
An authoring draft may be incomplete and need not be runnable. Preserve
unrequested fields and empty configuration groups when editing only names,
dates, or settings. Never add factors, products, or groups merely to satisfy
run readiness; report a validation blocker rather than expanding the request.
For a test configuration, inspect the registered `configurations` node before
creating a strategy or configuration group. Its `collection_path`,
`create_template`, `required_fields`, `field_sources`, and `item_schema` are
the authoritative contract. Copy that template, replace its placeholders from
the registered candidate sources, and do not guess keys or probe validation
one field at a time. For backtest strategies, obey its `batch_contract`:
all members of one N-group partition share one `batchId` and vary only their
`groupIndex` from 1 through `splitCount`. Never patch either schema_version and never add
local_settings or analysis-level settings; the current draft already carries
the authoritative document envelope and registered UI setting structure.
Apply the structured change once with
`factortester assist drafts patch <draft-id> --stdin`, validate it with
`factortester assist drafts validate <draft-id>`, then apply it atomically with
`factortester assist drafts apply <draft-id>`.
Node values and complete draft documents are omitted by default. Request a
node value with `assist inspect --node <node-id> --value` only when needed.
Use `assist drafts show <draft-id> --document` only for explicit diagnosis;
do not read assistance draft storage files directly.
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
    if assistance_store.current(principal, profile_id) is None and not assistance_store.workspace(principal, profile_id):
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
    def _assistance_is_self(self, principal: str, profile_id: str) -> bool:
        profile = self._profile(principal, profile_id) or {}
        return profile_id == "self" or profile.get("is_self_profile") is True or profile.get("profile_kind") == "self"

    def _assistance_visible_workspace(self, principal: str, profile_id: str, workspace: dict) -> dict:
        if self._assistance_is_self(principal, profile_id):
            return workspace
        visible = []
        allowed = {}
        for tab in workspace.get("tabs") or []:
            research_id = str(tab.get("research_id") or "")
            if research_id and research_id not in allowed:
                try:
                    members = self._research_catalog_service().list_members(research_id, viewer=principal)
                    allowed[research_id] = any(
                        str(member.get("profile_ref") or "").removeprefix("profile:") == profile_id
                        for member in members
                    )
                except (KeyError, PermissionError):
                    allowed[research_id] = False
            if allowed.get(research_id):
                visible.append(tab)
        return {**workspace, "tabs": visible}

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
            workspace = _STORE.workspace(principal, profile_id)
            if workspace:
                _STORE.publish_workspace(principal, profile_id,
                    self._assistance_visible_workspace(principal, profile_id, workspace))
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
                        "page": (_STORE.page(principal, profile_id, query["tab_id"][0])
                                 if query.get("tab_id", [""])[0]
                                 else _STORE.current(principal, profile_id)),
                        "workspace": _STORE.workspace(principal, profile_id),
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
            "/api/client/profile-agent/assistance/drafts/patch",
        }:
            return False
        try:
            payload = self._json_body(2 * 1024 * 1024)
            principal, profile_id = self._agent_app_profile(
                str(payload.get("profile_id") or "")
            )
            workspace = _STORE.workspace(principal, profile_id)
            if workspace:
                _STORE.publish_workspace(principal, profile_id,
                    self._assistance_visible_workspace(principal, profile_id, workspace))
            if parsed.path.endswith("/drafts"):
                page = (_STORE.page(principal, profile_id, str(payload["tab_id"]))
                        if payload.get("tab_id") else _STORE.current(principal, profile_id))
                if not page:
                    raise ValueError("no assisted page is currently open")
                assistance = page["assistance"]
                document = (
                    assistance.get("document")
                    if payload.get("from_current") is True
                    else payload.get("document")
                )
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
            elif parsed.path.endswith("/drafts/patch"):
                patch = payload.get("patch")
                if not isinstance(patch, dict):
                    raise ValueError("assistance draft patch must be an object")
                item = (
                    self._agent_service()
                    .assistance_drafts(principal, profile_id)
                    .patch(str(payload.get("draft_id") or ""), patch)
                )
                json_response(self, {"success": True, "draft": item})
            elif parsed.path.endswith("/publish"):
                workspace = payload.get("workspace")
                if isinstance(workspace, dict):
                    workspace = self._assistance_visible_workspace(principal, profile_id, workspace)
                    _STORE.publish_workspace(principal, profile_id, workspace)
                    item = _STORE.page(principal, profile_id, str(payload.get("tab_id") or ""))
                else:
                    # Legacy page-only publication is restricted to self. Research
                    # scopes require explicit hierarchy to authorize the target.
                    if not self._assistance_is_self(principal, profile_id):
                        raise ValueError("research assistance requires workspace scope")
                    item = _STORE.publish(principal, profile_id, payload)
                json_response(self, {"success": True, "page": item})
            elif parsed.path.endswith("/validate"):
                draft_id = str(payload.get("draft_id") or "")
                drafts = self._agent_service().assistance_drafts(principal, profile_id)
                draft = drafts.get(draft_id)
                if draft.get("status") == "applied":
                    application = draft.get("application") or {}
                    json_response(self, {
                        "success": True,
                        "applied": {
                            "success": True,
                            "revision": application.get("applied_revision"),
                            "draft_id": draft_id,
                        },
                    })
                    return True
                try:
                    page = _STORE.resolve_target(
                        principal,
                        profile_id,
                        page_kind=str(draft.get("page_kind") or ""),
                        schema_version=int(
                            draft.get("document_schema_version") or 0
                        ),
                        document=draft.get("document"),
                        tab_id=str(draft.get("source_tab_id") or ""),
                    )
                except ValueError as exc:
                    drafts.set_status(draft_id, "rejected", error=str(exc))
                    raise
                drafts.set_status(
                    draft_id,
                    "validated",
                    target_tab_id=page["tab_id"],
                    target_revision=int(page["assistance"]["revision"]),
                )
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
                draft_id = str(result.get("draft_id") or "")
                if draft_id:
                    try:
                        drafts = self._agent_service().assistance_drafts(
                            principal, profile_id,
                        )
                        drafts.set_status(
                            draft_id,
                            "applied" if result["success"] else "rejected",
                            error=result.get("error") or "",
                            applied_revision=result.get("revision"),
                            target_tab_id=result.get("target_tab_id") or "",
                            target_revision=result.get("target_revision"),
                        )
                    except AssistanceDraftError:
                        pass
                json_response(self, {"success": True, "result": result})
            else:
                draft_id = str(payload.get("draft_id") or "")
                drafts = self._agent_service().assistance_drafts(principal, profile_id)
                draft = drafts.get(draft_id)
                try:
                    page = _STORE.resolve_target(
                        principal,
                        profile_id,
                        page_kind=str(draft.get("page_kind") or ""),
                        schema_version=int(
                            draft.get("document_schema_version") or 0
                        ),
                        document=draft.get("document"),
                        tab_id=str(draft.get("source_tab_id") or ""),
                    )
                    item = _STORE.enqueue(
                        principal,
                        profile_id,
                        {
                            "tab_id": page["tab_id"],
                            "expected_revision": page["assistance"]["revision"],
                            "document": draft.get("document"),
                            "draft_id": draft_id,
                        },
                    )
                    drafts.set_status(
                        draft_id,
                        "queued",
                        target_tab_id=page["tab_id"],
                        target_revision=int(page["assistance"]["revision"]),
                    )
                    try:
                        result = _STORE.wait_result(item["sequence"])
                    except TimeoutError:
                        json_response(
                            self,
                            {
                                "success": True,
                                "queued": True,
                                "sequence": item["sequence"],
                            },
                            202,
                        )
                        return True
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
