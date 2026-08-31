"""Canonical Manager routes for Research ownership and relationships."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote

from server.manager.http.responses import json_response


class ResearchCatalogRoutesMixin:
    """Expose the Research catalog without duplicating report/Evidence stores."""

    def _research_catalog_service(self):
        service = getattr(self.state, "research_catalog", None)
        if service is None:
            raise RuntimeError("Research catalog is unavailable")
        return service

    def _research_catalog_session(self):
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return None
        return session

    def _research_catalog_body(self, maximum: int = 2 * 1024 * 1024) -> dict:
        value = self._json_body(maximum)
        if not isinstance(value, dict):
            raise TypeError("request body must be an object")
        return value

    def _research_catalog_error(self, exc: Exception) -> None:
        if isinstance(exc, PermissionError):
            status = 403
        elif isinstance(exc, KeyError):
            status = 404
        elif isinstance(exc, (TypeError, ValueError)):
            status = 400
        else:
            status = 500
        json_response(self, {"success": False, "error": str(exc)}, status)

    def _get_research_catalog_routes(self, parsed) -> bool:
        if not self._is_research_catalog_path(parsed.path):
            return False
        session = self._research_catalog_session()
        if session is None:
            return True
        viewer = str(session["username"])
        service = self._research_catalog_service()
        query = parse_qs(parsed.query, keep_blank_values=True)
        try:
            if parsed.path == "/api/research":
                scope = str(query.get("scope", ["all"])[0] or "all")
                subordinate_refs = self._research_catalog_subordinate_refs(viewer)
                value = service.list_researches(
                    viewer=viewer,
                    include_archived=query.get("include_archived") == ["1"],
                    scope=scope,
                    subordinate_refs=subordinate_refs,
                )
                payload = {"researches": value, "items": value, "scope": scope}
            elif parsed.path == "/api/research/reports":
                scope = str(query.get("scope", ["all"])[0] or "all")
                value = service.list_reports_for_scope(
                    viewer=viewer,
                    include_archived=query.get("include_archived") == ["1"],
                    scope=scope,
                    subordinate_refs=self._research_catalog_subordinate_refs(viewer),
                )
                payload = {
                    "reports": value,
                    "items": value,
                    "count": len(value),
                    "scope": scope,
                }
            else:
                research_id, child = self._research_catalog_target(parsed.path)
                if child is None:
                    payload = {
                        "research": service.get_research_summary(
                            research_id, viewer=viewer,
                        ),
                    }
                elif child == "members":
                    payload = {
                        "members": service.list_members(
                            research_id, viewer=viewer,
                        ),
                    }
                elif child == "workspaces":
                    payload = {
                        "workspaces": service.list_workspaces(
                            research_id, viewer=viewer,
                        ),
                    }
                elif child == "reports":
                    payload = {
                        "reports": service.list_reports(
                            research_id, viewer=viewer,
                        ),
                    }
                elif child == "evidence":
                    payload = {
                        "evidence_links": service.list_evidence_links(
                            research_id, viewer=viewer,
                        ),
                    }
                else:
                    raise KeyError("research route not found")
        except (KeyError, PermissionError, TypeError, ValueError, RuntimeError) as exc:
            self._research_catalog_error(exc)
            return True
        json_response(self, {"success": True, **payload})
        return True

    def _post_research_catalog_routes(self, parsed) -> bool:
        if not self._is_research_catalog_path(parsed.path):
            return False
        session = self._research_catalog_session()
        if session is None:
            return True
        actor = str(session["username"])
        service = self._research_catalog_service()
        try:
            data = self._research_catalog_body()
            if parsed.path == "/api/research":
                value = service.create_research(
                    owner_ref=actor,
                    title=data.get("title"),
                    description=str(data.get("description") or ""),
                    visibility=str(data.get("visibility") or "private"),
                    authorized_users=data.get("authorized_users"),
                    profile_ref=str(data.get("profile_ref") or ""),
                )
                json_response(self, {"success": True, "research": value}, 201)
                return True
            if parsed.path == "/api/research/migrations/reports":
                value = service.migrate_reports(
                    list(data.get("records") or []), actor=actor,
                )
                json_response(self, {"success": True, **value}, 200)
                return True
            research_id, child = self._research_catalog_target(parsed.path)
            if child == "members":
                value = service.add_membership(
                    research_id,
                    actor=actor,
                    principal_ref=data.get("principal_ref"),
                    profile_ref=data.get("profile_ref"),
                    role=str(data.get("role") or "contributor"),
                    status=str(data.get("status") or "active"),
                )
                json_response(self, {"success": True, "member": value}, 201)
                return True
            if child == "workspaces":
                value = service.create_workspace(
                    research_id,
                    actor=actor,
                    principal_ref=data.get("principal_ref") or actor,
                    profile_ref=data.get("profile_ref"),
                    title=str(data.get("title") or ""),
                )
                json_response(self, {"success": True, "workspace": value}, 201)
                return True
            if child == "reports":
                value = service.register_report(
                    research_id,
                    actor=actor,
                    report_id=data.get("report_id"),
                    title=str(data.get("title") or ""),
                    profile_ref=str(data.get("profile_ref") or ""),
                    workspace_id=str(data.get("workspace_id") or ""),
                    build_source=str(data.get("build_source") or "client"),
                    build_source_ref=str(data.get("build_source_ref") or ""),
                    visibility=str(data.get("visibility") or "private"),
                    authorized_users=data.get("authorized_users"),
                    source_ref=str(data.get("source_ref") or ""),
                )
                json_response(self, {"success": True, "report": value}, 201)
                return True
            if child == "evidence":
                value = service.link_evidence(
                    research_id,
                    actor=actor,
                    evidence_ref=data.get("evidence_ref"),
                    evidence_owner_ref=str(data.get("evidence_owner_ref") or ""),
                    report_id=str(data.get("report_id") or ""),
                    graph_ref=str(data.get("graph_ref") or ""),
                    branch_ref=str(data.get("branch_ref") or ""),
                    job_id=str(data.get("job_id") or ""),
                    profile_ref=str(data.get("profile_ref") or ""),
                    purpose=str(data.get("purpose") or ""),
                )
                json_response(self, {"success": True, "evidence_link": value}, 201)
                return True
            raise KeyError("research route not found")
        except (KeyError, PermissionError, TypeError, ValueError, RuntimeError) as exc:
            self._research_catalog_error(exc)
            return True

    def _patch_research_catalog_routes(self, parsed) -> bool:
        match = re.fullmatch(r"/api/research/([^/]+)", parsed.path)
        if not match:
            return False
        session = self._research_catalog_session()
        if session is None:
            return True
        try:
            data = self._research_catalog_body()
            value = self._research_catalog_service().update_research(
                unquote(match.group(1)),
                actor=str(session["username"]),
                title=data.get("title"),
                description=data.get("description"),
                visibility=data.get("visibility"),
                authorized_users=data.get("authorized_users"),
                status=data.get("status"),
            )
        except (KeyError, PermissionError, TypeError, ValueError, RuntimeError) as exc:
            self._research_catalog_error(exc)
            return True
        json_response(self, {"success": True, "research": value})
        return True

    @staticmethod
    def _is_research_catalog_path(path: str) -> bool:
        return path == "/api/research" or path.startswith("/api/research/")

    def _research_catalog_subordinate_refs(self, viewer: str) -> list[str]:
        subordinate_users = self._subordinate_users(viewer)
        return [
            str(item.get("username") or item.get("owner_ref") or "").strip()
            for item in subordinate_users
            if isinstance(item, dict)
        ]

    @staticmethod
    def _research_catalog_target(path: str) -> tuple[str, str | None]:
        match = re.fullmatch(
            r"/api/research/([^/]+)(?:/(members|workspaces|reports|evidence))?",
            path,
        )
        if not match:
            raise KeyError("research route not found")
        return unquote(match.group(1)), match.group(2)


__all__ = ["ResearchCatalogRoutesMixin"]
