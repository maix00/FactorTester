"""Ephemeral structured-document transport for page-scoped Profile Agents."""

from __future__ import annotations

import re
import secrets
import hashlib
import json
import time
from copy import deepcopy
from threading import Condition, RLock
from urllib.parse import parse_qs

from server.manager.http.responses import json_response
from server.manager.services.assistance_drafts import AssistanceDraftError
from server.services import research_configurations


def validate_document(schema: dict, value: object, path: str = "$") -> None:
    if path == "$" and schema.get("readOnly") is True:
        raise ValueError("assisted page is read-only")
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


class WorkspaceRevisionConflict(ValueError):
    """A newer browser workspace operation already won."""


class WorkspaceLeaseExpired(PermissionError):
    """An issued workspace no longer exists or is not owned by this caller."""


class PageAssistanceStore:
    def __init__(self, *, ttl_seconds: float = 900.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = RLock()
        self._condition = Condition(self._lock)
        self._contexts: dict[tuple[str, str, str], dict] = {}
        self._applications: dict[tuple[str, str, str], list[dict]] = {}
        self._workspaces: dict[tuple[str, str], dict] = {}
        self._workspace_leases: dict[tuple[str, str, str], float] = {}
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
        for key, expiry in list(self._workspace_leases.items()):
            if expiry < time.time():
                self._workspace_leases.pop(key, None)
        for key in stale:
            self._contexts.pop(key, None)
            self._applications.pop(key, None)

    def issue_workspace(self, principal: str, profile_id: str) -> str:
        """Issue a per-browser opaque lease; never reuse a client-supplied ID."""
        with self._condition:
            self._prune()
            if (len(self._workspace_leases) >= 4096 or
                    sum(key[:2] == (principal, profile_id) for key in self._workspace_leases) >= 32):
                raise RuntimeError("assistance workspace capacity is reached")
            workspace_id = secrets.token_urlsafe(24)
            self._workspace_leases[(principal, profile_id, workspace_id)] = time.time() + self.ttl_seconds
            return workspace_id

    def workspace_scope(self, principal: str, profile_id: str, workspace_id: str) -> str:
        value = str(workspace_id or "").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{32}", value) is None:
            raise WorkspaceLeaseExpired("an issued workspace is required")
        with self._condition:
            self._prune()
            key = (principal, profile_id, value)
            if key not in self._workspace_leases:
                raise WorkspaceLeaseExpired("workspace is invalid or expired")
            self._workspace_leases[key] = time.time() + self.ttl_seconds
        return profile_id + "\0" + value

    def _require_live_scope(self, principal: str, scoped_profile: str) -> None:
        if "\0" not in scoped_profile:
            return  # direct store-only use, never exposed by the HTTP adapter
        profile_id, workspace_id = scoped_profile.split("\0", 1)
        if self._workspace_leases.get((principal, profile_id, workspace_id), 0) < time.time():
            raise WorkspaceLeaseExpired("workspace is invalid or expired")

    def release_workspace(self, principal: str, profile_id: str, workspace_id: str) -> None:
        scoped = self.workspace_scope(principal, profile_id, workspace_id)
        with self._condition:
            self._workspace_leases.pop((principal, profile_id, workspace_id), None)
            self._workspaces.pop((principal, scoped), None)
            for key in list(self._contexts):
                if key[:2] == (principal, scoped):
                    self._contexts.pop(key, None)
                    self._applications.pop(key, None)
            self._condition.notify_all()

    def remove_page(self, principal: str, scoped_profile: str, tab_id: str, *, client_revision: int) -> None:
        target = str(tab_id or "").strip()
        if not target:
            raise ValueError("tab_id is required")
        with self._condition:
            self._require_live_scope(principal, scoped_profile)
            workspace = self._workspaces.setdefault((principal, scoped_profile), {"tabs": []})
            self._check_client_revision(workspace, client_revision, "delete:" + target)
            self._contexts.pop((principal, scoped_profile, target), None)
            self._applications.pop((principal, scoped_profile, target), None)
            if workspace:
                workspace["tabs"] = [tab for tab in workspace.get("tabs", []) if tab.get("tab_id") != target]
                if workspace.get("active_tab_id") == target:
                    workspace["active_tab_id"] = None
                workspace["_store_revision"] = int(workspace.get("_store_revision") or 0) + 1
                workspace["updated_at"] = time.time()

    @staticmethod
    def _check_client_revision(previous: dict, revision: int, digest: str) -> None:
        if type(revision) is not int or revision < 1:
            raise ValueError("workspace client_revision must be a positive integer")
        old = int(previous.get("client_revision") or 0)
        if revision < old or (revision == old and previous.get("_client_digest") != digest):
            raise WorkspaceRevisionConflict("workspace has a newer revision")
        previous["client_revision"], previous["_client_digest"] = revision, digest

    def restrict_workspace(self, principal: str, scoped_profile: str, *,
                           expected_revision: int, allowed_tab_ids: set[str]) -> bool:
        """Remove denied pages only if the inspected snapshot is still current."""
        with self._condition:
            self._require_live_scope(principal, scoped_profile)
            workspace = self._workspaces.get((principal, scoped_profile))
            if workspace is None:
                return True
            if int(workspace.get("_store_revision") or 0) != expected_revision:
                return False
            removed = {str(tab.get("tab_id") or "") for tab in workspace.get("tabs", [])} - allowed_tab_ids
            if not removed:
                return True
            workspace["tabs"] = [tab for tab in workspace.get("tabs", []) if tab.get("tab_id") in allowed_tab_ids]
            if workspace.get("active_tab_id") in removed:
                workspace["active_tab_id"] = None
            for tab_id in removed:
                self._contexts.pop((principal, scoped_profile, tab_id), None)
                self._applications.pop((principal, scoped_profile, tab_id), None)
            workspace["_store_revision"] = expected_revision + 1
            return True

    def publish_workspace(self, principal: str, profile_id: str, workspace: dict) -> None:
        tabs = workspace.get("tabs") or []
        if not isinstance(tabs, list) or len(tabs) > 1000:
            raise ValueError("too many workspace tabs")
        for tab in tabs:
            if not isinstance(tab, dict) or not str(tab.get("tab_id") or "").strip():
                raise ValueError("workspace tab is invalid")
            assistance = tab.get("assistance")
            if assistance is not None:
                if not isinstance(assistance, dict) or int(assistance.get("schema_version") or 0) != 1:
                    raise ValueError("unsupported page assistance schema")
                validate_navigation(assistance.get("navigation"))
        tab_ids = {str(tab["tab_id"]) for tab in tabs}
        with self._condition:
            self._require_live_scope(principal, profile_id)
            previous = self._workspaces.get((principal, profile_id), {})
            client_revision = workspace.get("client_revision")
            if client_revision is not None:
                digest = hashlib.sha256(json.dumps(workspace, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":")).encode()).hexdigest()
                self._check_client_revision(previous, client_revision, digest)
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
            self._workspaces[(principal, profile_id)] = {
                "updated_at": time.time() if any("assistance" in tab for tab in tabs)
                              else previous.get("updated_at", time.time()),
                "active_tab_id": workspace.get("active_tab_id") if workspace.get("active_tab_id") in tab_ids else None,
                "tabs": [{**{key: tab.get(key) for key in (
                    "tab_id", "title", "path", "kind", "research_id", "parent_tab_id", "_research_ids")},
                    "writable": (bool(tab.get("assistance")) and not (tab["assistance"].get("document_schema") or {}).get("readOnly")) if "assistance" in tab else bool(tab.get("writable"))}
                    for tab in tabs],
                "client_revision": previous.get("client_revision", 0),
                "_client_digest": previous.get("_client_digest", ""),
                "_store_revision": int(previous.get("_store_revision") or 0) + 1,
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

class PageAssistanceRoutesMixin:
    def _assistance_error(self, exc: Exception) -> None:
        from server.identity.keycloak_authorization import AuthorizationUnavailable
        if isinstance(exc, WorkspaceLeaseExpired):
            json_response(self, {"success": False, "code": "assistance_workspace_expired", "error": str(exc)}, 403)
        elif isinstance(exc, AuthorizationUnavailable):
            json_response(self, {"success": False, "code": "authorization_unavailable", "error": str(exc)}, 503)
        elif isinstance(exc, PermissionError):
            json_response(self, {"success": False, "code": "permission_denied", "error": str(exc)}, 403)
        elif isinstance(exc, WorkspaceRevisionConflict):
            json_response(self, {"success": False, "code": "workspace_revision_conflict", "error": str(exc)}, 409)
        else:
            self._agent_app_error(exc)

    def _assistance_profile(self, profile_id: str, workspace_id: str) -> tuple[str, str, str]:
        """Bind browser requests or an Agent's exact active-turn delegation."""
        from server.identity.request_context import bind_verified_identity
        from server.identity.server_admission import server_admission
        from server.identity.user_session import keycloak_session
        from server.permissions.agent_assistant import can_use_agent_assistant

        session = self._session()
        if not isinstance(session, dict):
            raise PermissionError("login required")
        if session.get("authentication") != "agent":
            principal, identifier = self._agent_app_profile(profile_id)
            return principal, identifier, str(workspace_id or "").strip()
        if not self._is_local_agent_request():
            raise PermissionError("verified local Agent capability is required")
        principal, identifier = self._agent_principal(session), str(profile_id or "").strip()
        if identifier != str(self.headers.get("X-FactorTester-Agent-Profile", "")).strip():
            raise PermissionError("Agent capability belongs to another Profile")
        binding = self._agent_app_server().assistance_turn_binding(principal, identifier)
        if not isinstance(binding, dict):
            raise PermissionError("Agent has no active workspace-bound turn")
        target = str(binding.get("workspace_id") or "").strip()
        if workspace_id and str(workspace_id).strip() != target:
            raise PermissionError("Agent turn belongs to another workspace")
        token = str(binding.get("token") or "")
        user = keycloak_session(token, use_cache=False, fail_on_unavailable=True)
        if (not isinstance(user, dict) or str(user.get("username") or "") != principal
                or str(user.get("keycloak_subject") or "") != binding.get("subject")
                or str(user.get("keycloak_issuer") or "") != binding.get("issuer")
                or str(user.get("tr_identity_id") or "") != binding.get("identity_id")
                or not server_admission(user, state=self.state, use_cache=False)[0]
                or not can_use_agent_assistant(user)):
            raise PermissionError("delegated Keycloak session is no longer authorized")
        if not self._profile_exists(principal, identifier):
            raise PermissionError("Profile does not belong to current account")
        self._agent_service().require_local_server_runtime(principal, identifier)
        bind_verified_identity(token, user)
        return principal, identifier, target

    def _assistance_refresh_workspace(self, principal: str, profile_id: str, scoped_profile: str) -> dict:
        for _ in range(3):
            workspace = _STORE.workspace(principal, scoped_profile)
            if not workspace:
                return {}
            visible = self._assistance_visible_workspace(principal, profile_id, workspace, stored=True)
            if _STORE.restrict_workspace(principal, scoped_profile,
                    expected_revision=int(workspace.get("_store_revision") or 0),
                    allowed_tab_ids={str(tab["tab_id"]) for tab in visible["tabs"]}):
                return _STORE.workspace(principal, scoped_profile)
        raise WorkspaceRevisionConflict("workspace changed while authorizing; retry")

    @staticmethod
    def _assistance_checked_draft(store, draft_id: str, workspace_id: str, workspace: dict) -> dict:
        draft = store.get(draft_id)
        allowed_tabs = {str(tab.get("tab_id") or "") for tab in workspace.get("tabs", [])}
        if (str(draft.get("session_id") or "") != workspace_id
                or str(draft.get("source_tab_id") or "") not in allowed_tabs):
            raise PermissionError("draft is outside the authorized workspace")
        return draft

    def _assistance_is_self(self, principal: str, profile_id: str) -> bool:
        if profile_id == "self":
            return True
        profile = self._profile(principal, profile_id) or {}
        return profile.get("is_self_profile") is True or profile.get("profile_kind") == "self"

    def _assistance_visible_workspace(self, principal: str, profile_id: str, workspace: dict, *, stored=False) -> dict:
        """Recheck every referenced Research using this user's current KC grants."""
        from server.identity.keycloak_research import KeycloakResearchAuthorization, verified_research_request
        from tools.data.sqlite.db import connect_sqlite

        if verified_research_request(principal) is None:
            raise PermissionError("verified Keycloak identity is required")
        tabs = workspace.get("tabs") or []
        if not isinstance(tabs, list) or len(tabs) > 1000:
            raise ValueError("workspace tabs are invalid")
        indexed = {}
        def references(value, depth=0):
            if depth > 32:
                raise ValueError("workspace context nesting is too deep")
            result = set()
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "research_id" and isinstance(item, str):
                        ref = item.strip()
                        if len(ref) > 512:
                            raise ValueError("Research reference is invalid")
                        if ref:
                            result.add(ref)
                    elif key == "research_id" and item is not None and not isinstance(item, (dict, list)):
                        raise ValueError("Research reference is invalid")
                    elif key != "_research_ids":
                        result.update(references(item, depth + 1))
            elif isinstance(value, list):
                for item in value:
                    result.update(references(item, depth + 1))
            return result
        for tab in tabs:
            if not isinstance(tab, dict):
                raise ValueError("workspace tab is invalid")
            tab_id = str(tab.get("tab_id") or "").strip()
            if not tab_id or len(tab_id) > 256 or tab_id in indexed:
                raise ValueError("workspace tab identity is invalid or duplicated")
            own = references(tab)
            if stored:
                original = tab.get("_research_ids") or []
                if not isinstance(original, list) or any(not isinstance(ref, str) for ref in original):
                    raise ValueError("stored Research references are invalid")
                own.update(original)
            indexed[tab_id] = (tab, own)

        def all_refs(tab_id, seen):
            if tab_id in seen:
                raise ValueError("workspace parent cycle is invalid")
            tab, own = indexed[tab_id]
            parent = str(tab.get("parent_tab_id") or "").strip()
            if parent and parent not in indexed:
                raise ValueError("workspace parent is missing")
            return own | (all_refs(parent, seen | {tab_id}) if parent else set())

        refs_by_tab = {tab_id: all_refs(tab_id, set()) for tab_id in indexed}
        # A page labelled as Research is never treated as an unscoped page.
        # In particular an omitted or malformed identifier cannot bypass UMA.
        for tab_id, (tab, _own) in indexed.items():
            assistance = tab.get("assistance") or {}
            if (tab.get("kind") == "research" or
                    isinstance(assistance, dict) and assistance.get("page_kind") == "research"):
                if not refs_by_tab[tab_id]:
                    raise ValueError("Research page requires a Research reference")
        refs = set().union(*refs_by_tab.values()) if refs_by_tab else set()
        if len(refs) > 1000:
            raise ValueError("workspace contains too many Research references")
        is_self = self._assistance_is_self(principal, profile_id)
        if not refs:
            return {**workspace, "tabs": [{**tab, "_research_ids": []}
                                            for tab, _own in indexed.values()] if is_self else []}
        catalog = self._research_catalog_service()
        statuses = catalog.research_statuses(refs)
        rows = sorted(statuses.items())
        auth = KeycloakResearchAuthorization()
        direct = auth.research_access_many(viewer=principal, researches=rows)
        memberships = {}
        if refs and getattr(catalog, "_profile_authorizer", None) is not None:
            with connect_sqlite(catalog.db_path, readonly=True) as db:
                pairs = catalog._profile_pairs(db, principal)
            pairs = {pair: revision for pair, revision in pairs.items()
                     if pair[0] in refs and pair[1].removeprefix("profile:") == profile_id}
            memberships = catalog._profile_membership_access(principal, pairs)
        allowed = {ref for ref, status in rows if
                   (status == "active" and memberships.get(ref, {}).get("can_view")) or
                   (is_self and direct.get(ref, {}).get("can_view"))}
        visible = []
        for tab_id, (tab, _own) in indexed.items():
            research_ids = refs_by_tab[tab_id]
            if research_ids.issubset(allowed) and (is_self or research_ids):
                visible.append({**tab, "_research_ids": sorted(research_ids)})
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
            principal, profile_id, workspace_id = self._assistance_profile(
                query.get("profile_id", [""])[0], query.get("workspace_id", [""])[0])
            scoped_profile = _STORE.workspace_scope(principal, profile_id, workspace_id)
            workspace = self._assistance_refresh_workspace(principal, profile_id, scoped_profile)
            if parsed.path.endswith("/drafts"):
                store = self._agent_service().assistance_drafts(principal, profile_id)
                draft_id = query.get("draft_id", [""])[0]
                if draft_id:
                    value = {"draft": self._assistance_checked_draft(store, draft_id, workspace_id, workspace)}
                else:
                    value = store.list()
                    allowed_tabs = {str(tab.get("tab_id") or "") for tab in workspace.get("tabs", [])}
                    value["drafts"] = [draft for draft in value.get("drafts", [])
                        if str(draft.get("session_id") or "") == workspace_id
                        and str(draft.get("source_tab_id") or "") in allowed_tabs]
                json_response(self, {"success": True, **value})
            elif parsed.path.endswith("/applications"):
                values = _STORE.applications(
                    principal,
                    scoped_profile,
                    query.get("tab_id", [""])[0],
                    int(query.get("after", ["0"])[0] or 0),
                    float(query.get("wait", ["0"])[0] or 0),
                )
                workspace = self._assistance_refresh_workspace(principal, profile_id, scoped_profile)
                allowed = {str(tab["tab_id"]) for tab in workspace.get("tabs", [])}
                values = [item for item in values if str(item.get("tab_id") or "") in allowed]
                json_response(self, {"success": True, "applications": values})
            else:
                json_response(
                    self,
                    {
                        "success": True,
                        "profile_id": profile_id,
                        "page": (_STORE.page(principal, scoped_profile, query["tab_id"][0])
                                 if query.get("tab_id", [""])[0]
                                 else _STORE.current(principal, scoped_profile)),
                        "workspace": {key: value for key, value in workspace.items() if not key.startswith("_")},
                    },
                )
        except (AssistanceDraftError, PermissionError, RuntimeError, TypeError, ValueError) as exc:
            self._assistance_error(exc)
        return True

    def _post_page_assistance_routes(self, parsed) -> bool:
        if parsed.path not in {
            "/api/client/profile-agent/assistance/workspaces",
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
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            if parsed.path.endswith("/workspaces"):
                principal, profile_id = self._agent_app_profile(str(payload.get("profile_id") or ""))
                json_response(self, {"success": True, "workspace_id": _STORE.issue_workspace(principal, profile_id)}, 201)
                return True
            principal, profile_id, workspace_id = self._assistance_profile(
                str(payload.get("profile_id") or ""), str(payload.get("workspace_id") or ""))
            scoped_profile = _STORE.workspace_scope(principal, profile_id, workspace_id)
            workspace = self._assistance_refresh_workspace(principal, profile_id, scoped_profile)
            if parsed.path.endswith("/drafts"):
                page = (_STORE.page(principal, scoped_profile, str(payload["tab_id"]))
                        if payload.get("tab_id") else _STORE.current(principal, scoped_profile))
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
                        session_id=workspace_id,
                    )
                )
                json_response(self, {"success": True, "draft": item}, 201)
            elif parsed.path.endswith("/drafts/patch"):
                patch = payload.get("patch")
                if not isinstance(patch, dict):
                    raise ValueError("assistance draft patch must be an object")
                drafts = self._agent_service().assistance_drafts(principal, profile_id)
                self._assistance_checked_draft(drafts, str(payload.get("draft_id") or ""), workspace_id, workspace)
                item = drafts.patch(str(payload.get("draft_id") or ""), patch)
                json_response(self, {"success": True, "draft": item})
            elif parsed.path.endswith("/publish"):
                workspace = payload.get("workspace")
                if isinstance(workspace, dict):
                    if type(workspace.get("client_revision")) is not int or workspace["client_revision"] < 1:
                        raise ValueError("workspace client_revision is required")
                    workspace = self._assistance_visible_workspace(principal, profile_id, workspace)
                    _STORE.publish_workspace(principal, scoped_profile, workspace)
                    item = _STORE.page(principal, scoped_profile, str(payload.get("tab_id") or ""))
                else:
                    raise ValueError("workspace scope is required")
                json_response(self, {"success": True, "page": item})
            elif parsed.path.endswith("/validate"):
                draft_id = str(payload.get("draft_id") or "")
                drafts = self._agent_service().assistance_drafts(principal, profile_id)
                draft = self._assistance_checked_draft(drafts, draft_id, workspace_id, workspace)
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
                        scoped_profile,
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
                result = _STORE.acknowledge(principal, scoped_profile, payload)
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
                draft = self._assistance_checked_draft(drafts, draft_id, workspace_id, workspace)
                try:
                    page = _STORE.resolve_target(
                        principal,
                        scoped_profile,
                        page_kind=str(draft.get("page_kind") or ""),
                        schema_version=int(
                            draft.get("document_schema_version") or 0
                        ),
                        document=draft.get("document"),
                        tab_id=str(draft.get("source_tab_id") or ""),
                    )
                    item = _STORE.enqueue(
                        principal,
                        scoped_profile,
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
        except (AssistanceDraftError, PermissionError, RuntimeError, TypeError, ValueError) as exc:
            self._assistance_error(exc)
        return True

    def _delete_page_assistance_routes(self, parsed) -> bool:
        if parsed.path not in {"/api/client/profile-agent/assistance/drafts",
                               "/api/client/profile-agent/assistance/page",
                               "/api/client/profile-agent/assistance/workspaces"}:
            return False
        try:
            payload = parse_qs(parsed.query, keep_blank_values=True)
            principal, profile_id, workspace_id = self._assistance_profile(
                payload.get("profile_id", [""])[0], payload.get("workspace_id", [""])[0])
            if parsed.path.endswith("/workspaces"):
                self._agent_app_server().release_assistance_workspace(principal, profile_id, workspace_id)
                json_response(self, {"success": True, "deleted": True})
                return True
            scoped_profile = _STORE.workspace_scope(principal, profile_id, workspace_id)
            if parsed.path.endswith("/page"):
                _STORE.remove_page(principal, scoped_profile, payload.get("tab_id", [""])[0],
                                   client_revision=int(payload.get("client_revision", ["0"])[0]))
                json_response(self, {"success": True, "deleted": True})
                return True
            workspace = self._assistance_refresh_workspace(principal, profile_id, scoped_profile)
            store = self._agent_service().assistance_drafts(principal, profile_id)
            draft_id = payload.get("draft_id", [""])[0]
            self._assistance_checked_draft(store, draft_id, workspace_id, workspace)
            deleted = store.delete(draft_id)
            json_response(self, {"success": True, "deleted": deleted})
        except (AssistanceDraftError, PermissionError, RuntimeError, TypeError, ValueError) as exc:
            self._assistance_error(exc)
        return True
