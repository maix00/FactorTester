"""Canonical Manager routes for Research ownership and relationships."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, unquote

from server.manager.http.responses import json_response


class ResearchCatalogRoutesMixin:
    """Expose the Research catalog without duplicating report/Evidence stores."""

    def _research_catalog_service(self):
        service = getattr(self.state, "research_catalog", None)
        if service is None:
            raise RuntimeError("Research catalog is unavailable")
        return service

    def _refresh_research_catalog(self, principal: str) -> None:
        client = getattr(self.state, "client_state", None)
        if client is not None:
            client._refresh_account_domain_async(principal)

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
        self._refresh_research_catalog(viewer)
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
            elif parsed.path == "/api/research/principals":
                needle = str(query.get("q", [""])[0]).strip().casefold()
                relation = str(query.get("relation", [""])[0]).strip()
                superior_refs = set(
                    self._research_catalog_superior_refs(viewer)
                    if relation == "superiors" else []
                )
                values = []
                store = getattr(self.state, "control_store", None)
                for item in ([] if store is None else store.load_accounts()):
                    username = str(item.get("username") or "").strip()
                    if (
                        not username or username == viewer
                        or item.get("active", True) is False
                        or (relation == "superiors" and username not in superior_refs)
                        or (needle and needle not in username.casefold())
                    ):
                        continue
                    values.append({"principal_ref": username, "label": username})
                payload = {"principals": sorted(values, key=lambda item: item["label"])[:100]}
            elif parsed.path == "/api/research/reports":
                scope = str(query.get("scope", ["all"])[0] or "all")
                value = service.list_reports_for_scope(
                    viewer=viewer,
                    include_archived=query.get("include_archived") == ["1"],
                    scope=scope,
                    subordinate_refs=self._research_catalog_subordinate_refs(viewer),
                )
                value = self._research_catalog_publication_branches(value, viewer)
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
                    reports = service.list_reports(
                        research_id, viewer=viewer,
                    )
                    payload = {
                        "reports": self._research_catalog_publication_branches(
                            reports, viewer,
                        ),
                    }
                elif child == "evidence":
                    payload = {
                        "evidence_links": service.list_evidence_links(
                            research_id, viewer=viewer,
                        ),
                    }
                elif child == "collaboration-branches":
                    # Group-A (owner/editor) branches for every report in this
                    # research.  The catalog's ``_report_branches`` already
                    # projects branch choices from migrated source records
                    # (client / server_agent / publication), which includes
                    # branches synced from other servers and clients.  We do
                    # NOT re-scan the local workspaces here: a collaboration
                    # branch is visible through the shared catalog registry,
                    # even when its bytes live on another server or client.
                    reports = service.list_reports(
                        research_id, viewer=viewer,
                    )
                    seen: set[str] = set()
                    branches: list[dict[str, Any]] = []
                    for rep in reports:
                        for br in rep.get("branches") or []:
                            publication_id = str(
                                br.get("publication_id") or "",
                            ).strip()
                            if not publication_id or publication_id in seen:
                                continue
                            seen.add(publication_id)
                            branches.append({
                                **br,
                                "report_id": str(rep.get("report_id") or ""),
                                "research_id": research_id,
                                "profile_ref": str(
                                    br.get("profile_ref") or ""
                                ),
                            })
                    payload = {"branches": branches}
                elif child == "manifest":
                    manifest = service.research_manifest(
                        research_id, viewer=viewer,
                    )
                    manifest["source_server_id"] = str(self.state.server_id)
                    payload = {"manifest": manifest}
                elif child == "share-links":
                    payload = {
                        "share_links": service.list_share_links(
                            research_id, actor=viewer,
                        ),
                    }
                else:
                    raise KeyError("research route not found")
        except (KeyError, PermissionError, TypeError, ValueError, RuntimeError) as exc:
            self._research_catalog_error(exc)
            return True
        json_response(self, {"success": True, **payload})
        return True

    def _research_catalog_publication_branches(
        self, reports: list[dict], viewer: str,
    ) -> list[dict]:
        """Attach readable server projections without loading report bytes."""
        try:
            publications = self._research_service().list_visible(viewer)
        except (AttributeError, ConnectionError, OSError, RuntimeError, ValueError):
            publications = []
        by_report: dict[str, list[dict]] = {}
        for item in publications:
            if not isinstance(item, dict):
                continue
            report_id = str(item.get("report_id") or "").strip()
            publication_id = str(item.get("publication_id") or "").strip()
            if report_id and publication_id:
                by_report.setdefault(report_id, []).append(item)
        result = []
        for original in reports:
            value = dict(original)
            local = [dict(item) for item in value.get("branches") or []]
            projected = []
            for item in by_report.get(str(value.get("report_id") or ""), []):
                projected.append({
                    "branch_ref": str(item.get("branch_ref") or ""),
                    "title": str(item.get("branch_ref") or item.get("title") or ""),
                    "profile_ref": str(item.get("profile_ref") or ""),
                    "source_kind": "publication",
                    "source_ref": str(item.get("publication_id") or ""),
                    "publication_id": str(item.get("publication_id") or ""),
                    "selected": not projected,
                })
            if projected:
                for item in local:
                    item["selected"] = False
            seen = {item["publication_id"] for item in projected}
            value["branches"] = projected + [
                item for item in local if item.get("publication_id") not in seen
            ]
            result.append(value)
        return result

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
            if parsed.path == "/api/research/share-links/redeem":
                value = service.redeem_share_link(
                    str(data.get("token") or ""), actor=actor,
                )
                json_response(self, {"success": True, "grant": value})
                return True
            if parsed.path == "/api/research/migrations/reports/discover":
                records = self._discover_research_report_records(actor)
                if not bool(data.get("apply")):
                    json_response(self, {
                        "success": True, "status": "planned",
                        "count": len(records), "records": records,
                    })
                    return True
                value = service.migrate_reports(records, actor=actor)
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
                if data.get("report_id"):
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
                else:
                    value = service.create_report_space(
                        research_id,
                        actor=actor,
                        title=str(data.get("title") or ""),
                        profile_ref=str(data.get("profile_ref") or ""),
                        visibility=str(data.get("visibility") or "private"),
                        authorized_users=data.get("authorized_users"),
                    )
                json_response(self, {"success": True, "report": value}, 201)
                return True
            if child == "share-links":
                value = service.create_share_link(
                    target_kind=str(data.get("target_kind") or "research"),
                    research_id=research_id,
                    report_id=str(data.get("report_id") or ""),
                    actor=actor,
                    mode=str(data.get("mode") or "permanent"),
                    expires_at=float(data.get("expires_at") or 0),
                )
                json_response(self, {"success": True, "share_link": value}, 201)
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
        share_match = re.fullmatch(
            r"/api/research/([^/]+)/share-links/([^/]+)", parsed.path,
        )
        if share_match:
            session = self._research_catalog_session()
            if session is None:
                return True
            try:
                data = self._research_catalog_body()
                if data.get("revoked") is not True:
                    raise ValueError("share link patch requires revoked=true")
                value = self._research_catalog_service().revoke_share_link(
                    unquote(share_match.group(1)),
                    unquote(share_match.group(2)),
                    actor=str(session["username"]),
                )
            except (KeyError, PermissionError, TypeError, ValueError, RuntimeError) as exc:
                self._research_catalog_error(exc)
                return True
            json_response(self, {"success": True, "share_link": value})
            return True
        report_match = re.fullmatch(
            r"/api/research/([^/]+)/reports/([^/]+)", parsed.path,
        )
        if report_match:
            session = self._research_catalog_session()
            if session is None:
                return True
            try:
                data = self._research_catalog_body()
                value = self._research_catalog_service().update_report(
                    unquote(report_match.group(1)),
                    unquote(report_match.group(2)),
                    actor=str(session["username"]),
                    visibility=data.get("visibility"),
                    authorized_users=data.get("authorized_users"),
                )
                self._sync_research_report_publications(
                    owner=str(session["username"]),
                    report_id=str(value["report_id"]),
                    visibility=str(value["visibility"]),
                    authorized_users=list(value.get("authorized_users") or []),
                )
            except (KeyError, PermissionError, TypeError, ValueError, RuntimeError) as exc:
                self._research_catalog_error(exc)
                return True
            json_response(self, {"success": True, "report": value})
            return True
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

    def _delete_research_catalog_routes(self, parsed) -> bool:
        research_match = re.fullmatch(r"/api/research/([^/]+)", parsed.path)
        report_match = re.fullmatch(
            r"/api/research/([^/]+)/reports/([^/]+)", parsed.path,
        )
        member_match = re.fullmatch(
            r"/api/research/([^/]+)/members/([^/]+)", parsed.path,
        )
        if not research_match and not report_match and not member_match:
            return False
        session = self._research_catalog_session()
        if session is None:
            return True
        actor = str(session["username"])
        try:
            if research_match:
                value = self._research_catalog_service().remove_research(
                    unquote(research_match.group(1)), actor=actor,
                )
                payload = {"research": value}
            elif report_match:
                value = self._research_catalog_service().remove_report(
                    unquote(report_match.group(1)),
                    unquote(report_match.group(2)),
                    actor=actor,
                )
                payload = {"report": value}
            else:
                value = self._research_catalog_service().remove_membership(
                    unquote(member_match.group(1)),
                    profile_ref=unquote(member_match.group(2)),
                    actor=actor,
                )
                payload = {"member": value}
        except (KeyError, PermissionError, TypeError, ValueError, RuntimeError) as exc:
            self._research_catalog_error(exc)
            return True
        json_response(self, {"success": True, **payload})
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

    def _research_catalog_superior_refs(self, viewer: str) -> list[str]:
        store = getattr(self.state, "control_store", None)
        accounts = [] if store is None else list(store.load_accounts())
        by_username = {
            str(item.get("username") or "").strip(): item
            for item in accounts if isinstance(item, dict)
        }
        result: list[str] = []
        current = str(viewer or "").strip()
        visited: set[str] = set()
        while current and current not in visited:
            visited.add(current)
            account = by_username.get(current)
            if account is None or account.get("active", True) is False:
                break
            parent = str(account.get("parent_username") or "").strip()
            superior = by_username.get(parent)
            if not parent or superior is None or superior.get("active", True) is False:
                break
            result.append(parent)
            current = parent
        return result

    def _sync_research_report_publications(
        self,
        *,
        owner: str,
        report_id: str,
        visibility: str,
        authorized_users: list[str],
    ) -> None:
        """Apply the canonical Report policy to each uploaded Branch."""
        users = list(authorized_users)
        if visibility == "superiors":
            users = self._research_catalog_superior_refs(owner)
        for publication in self.state.public_research.list_owner(owner):
            if str(publication.get("report_id") or "") != report_id:
                continue
            self.state.public_research.configure(
                owner_ref=owner,
                report_id=report_id,
                publication_key=str(publication.get("publication_key") or report_id),
                projection=None,
                visibility=visibility,
                auto_sync=bool(publication.get("auto_sync", True)),
                relay_local_files=bool(publication.get("relay_local_files", False)),
                authorized_users=users,
            )

    def _discover_research_report_records(self, actor: str) -> list[dict]:
        """Project all three existing report stores into one explicit plan."""
        records: list[dict] = []
        for item in self.state.client_state.local_research(actor):
            value = dict(item)
            value.update(
                source_kind="client",
                source_ref=str(item.get("local_ref") or ""),
                owner_ref=actor,
                profile_ref=str(item.get("profile_id") or ""),
            )
            records.append(value)
        for item in self.state.server_research.list_owner(actor):
            value = dict(item)
            value.update(
                source_kind="server_agent",
                source_ref=str(item.get("server_ref") or ""),
                owner_ref=actor,
                profile_ref=str(item.get("profile_id") or ""),
            )
            records.append(value)
        for item in self.state.public_research.list_owner(actor):
            value = dict(item)
            value.update(
                source_kind="publication",
                source_ref=str(item.get("publication_id") or ""),
                owner_ref=actor,
            )
            records.append(value)
        return sorted(
            records,
            key=lambda item: (
                str(item.get("source_kind") or ""),
                str(item.get("source_ref") or ""),
            ),
        )

    @staticmethod
    def _research_catalog_target(path: str) -> tuple[str, str | None]:
        match = re.fullmatch(
            r"/api/research/([^/]+)(?:/(members|workspaces|reports|evidence|manifest|share-links))?",
            path,
        )
        if not match:
            raise KeyError("research route not found")
        return unquote(match.group(1)), match.group(2)


__all__ = ["ResearchCatalogRoutesMixin"]
