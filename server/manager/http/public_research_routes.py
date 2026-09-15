"""Public research projection, chapter, and attachment GET routes."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote

from server.manager.http.responses import download_response, json_response
from server.manager.services.research_export import (
    document_identity,
    markdown_export,
)


def _publication_identity(
    research: Any,
    publication_id: str,
    projection: dict[str, Any],
    catalog: Any = None,
    viewer: str | None = None,
) -> dict[str, Any]:
    """Read the branch identity of the publication being exported.

    The projection describes the report; the catalog registration of the
    branch says who wrote that branch, and the publication record supplies
    whatever the registration does not know.
    """
    registered: dict[str, Any] = {}
    reader = getattr(catalog, "report_branch_identity", None)
    if callable(reader):
        try:
            value = reader(publication_id)
        except (AttributeError, KeyError, OSError, RuntimeError, ValueError):
            value = None
        if isinstance(value, dict):
            registered = value
    metadata: dict[str, Any] = {}
    reader = getattr(research, "publication_metadata", None)
    if callable(reader):
        try:
            value = reader(publication_id, viewer)
        except (KeyError, OSError, RuntimeError, ValueError):
            value = None
        if isinstance(value, dict):
            metadata = value
    return document_identity(
        branch=str(
            registered.get("branch_id") or metadata.get("branch_ref") or ""
        ),
        owner=str(
            registered.get("principal_ref")
            or registered.get("owner_ref")
            or metadata.get("owner_ref") or ""
        ),
        profile=str(
            registered.get("profile_ref") or metadata.get("profile_ref") or ""
        ),
        generation=projection.get("generation") or metadata.get("generation") or 0,
        revision=str(registered.get("revision") or ""),
        projection_hash=str(
            projection.get("projection_hash")
            or metadata.get("projection_hash") or ""
        ),
        report_id=str(
            registered.get("report_id")
            or projection.get("report_id")
            or metadata.get("report_id") or ""
        ),
    )


class PublicResearchRoutesMixin:
    """Serve bounded public research views and owner publication settings."""

    def _research_service(self):
        """Return the local or federated read-through research service."""
        service = getattr(self.state, "federated_public_research", None)
        return service if service is not None else self.state.public_research

    def _get_public_research_routes(self, parsed) -> bool:
        research = self._research_service()
        if parsed.path == "/api/public-research":
            session = self._session()
            viewer = str(session["username"]) if session else None
            scope = parse_qs(parsed.query, keep_blank_values=True).get("scope", [""])[0]
            reports = research.list_visible(viewer)
            if scope == "shared":
                reports = [item for item in reports if item.get("is_owned") is not True]
            elif scope == "subordinates":
                if not viewer:
                    reports = []
                else:
                    from server.manager.domain.accounts import manager_subordinate_users

                    subordinate_refs = set()
                    for item in manager_subordinate_users(viewer):
                        subordinate_refs.update({
                            str(item.get("username") or "").strip(),
                            str(item.get("alias") or "").strip(),
                        } - {""})
                    reports = [
                        item for item in reports
                        if str(item.get("owner_ref") or item.get("owner_username") or "").strip()
                        in subordinate_refs
                    ]
            json_response(self, {
                "reports": reports,
                "scope": scope or "all",
            })
            return True
        public_component_match = re.fullmatch(
            r"/api/public-research/([A-Za-z0-9_-]{20,64})/chapters/([^/]+)/components/([^/]+)",
            parsed.path,
        )
        if public_component_match:
            session = self._session()
            viewer = str(session["username"]) if session else None
            try:
                value = research.component(
                    public_component_match.group(1),
                    unquote(public_component_match.group(2)),
                    unquote(public_component_match.group(3)),
                    viewer,
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return True
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return True
            except (ConnectionError, OSError, RuntimeError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 503)
                return True
            json_response(self, {"success": True, **value})
            return True
        public_chapter_match = re.fullmatch(
            r"/api/public-research/([A-Za-z0-9_-]{20,64})/(index|chapters/[A-Za-z0-9_.:-]{1,256})",
            parsed.path,
        )
        if public_chapter_match:
            session = self._session()
            viewer = str(session["username"]) if session else None
            try:
                publication_id = public_chapter_match.group(1)
                suffix = public_chapter_match.group(2)
                if suffix == "index":
                    value = research.index(publication_id, viewer)
                else:
                    value = research.chapter(
                        publication_id, unquote(suffix.split("/", 1)[1]), viewer,
                        include_content=parse_qs(parsed.query).get("metadata") != ["1"],
                    )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return True
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return True
            except (ConnectionError, OSError, RuntimeError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 503)
                return True
            json_response(self, {"success": True, **value})
            return True
        public_match = re.fullmatch(
            r"/api/public-research/([A-Za-z0-9_-]{20,64})", parsed.path,
        )
        if public_match:
            session = self._session()
            viewer = str(session["username"]) if session else None
            try:
                value = research.projection(
                    public_match.group(1), viewer,
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return True
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return True
            except (ConnectionError, OSError, RuntimeError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 503)
                return True
            etag = '"' + str(value["projection_hash"]) + '"'
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.end_headers()
                return True
            self.send_response(200)
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "private, no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        public_export_match = re.fullmatch(
            r"/api/public-research/([A-Za-z0-9_-]{20,64})/export", parsed.path,
        )
        if public_export_match:
            session = self._session()
            viewer = str(session["username"]) if session else None
            try:
                value = research.projection(public_export_match.group(1), viewer)
                raw, content_type, filename = markdown_export(
                    value,
                    parse_qs(parsed.query).get("format", ["md"])[0] or "md",
                    identity=_publication_identity(
                        research, public_export_match.group(1), value,
                        getattr(self.state, "research_catalog", None), viewer,
                    ),
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return True
            except NotImplementedError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 501)
                return True
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return True
            except (ConnectionError, OSError, RuntimeError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 503)
                return True
            download_response(self, raw, content_type, filename)
            return True
        asset_match = re.fullmatch(
            r"/api/public-research/([A-Za-z0-9_-]{20,64})/assets/([A-Za-z0-9_-]{8,64})",
            parsed.path,
        )
        if asset_match:
            session = self._session()
            viewer = str(session["username"]) if session else None
            try:
                raw, content_type, filename = research.asset(
                    asset_match.group(1), asset_match.group(2), viewer,
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return True
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return True
            except (ConnectionError, OSError, RuntimeError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 503)
                return True
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'inline; filename="{filename}"')
            self.send_header("Cache-Control", "private, no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return True
        local_resource_match = re.fullmatch(
            r"/api/public-research/([A-Za-z0-9_-]{20,64})/local-resources/([a-f0-9]{24})",
            parsed.path,
        )
        if local_resource_match:
            session = self._session()
            viewer = str(session["username"]) if session else None
            try:
                raw, content_type, filename = research.local_resource(
                    local_resource_match.group(1), local_resource_match.group(2), viewer,
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return True
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return True
            except (ConnectionError, OSError, RuntimeError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 503)
                return True
            safe_filename = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name) or "resource"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            disposition = "inline" if parse_qs(parsed.query).get("inline") == ["1"] else "attachment"
            self.send_header("Content-Disposition", f'{disposition}; filename="{safe_filename}"')
            self.send_header("Cache-Control", "private, no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return True
        attachment_match = re.fullmatch(
            r"/api/public-research/([A-Za-z0-9_-]{20,64})/attachments/(?:attachment%3Asha256%3A|attachment:sha256:)?([a-f0-9]{64})",
            parsed.path,
        )
        if attachment_match:
            session = self._session()
            viewer = str(session["username"]) if session else None
            try:
                raw, content_type, filename = research.attachment(
                    attachment_match.group(1),
                    f"attachment:sha256:{attachment_match.group(2)}",
                    viewer,
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return True
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return True
            except (ConnectionError, OSError, RuntimeError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 503)
                return True
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "private, no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return True
        if parsed.path == "/api/research-publications/settings":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            owner = str(session["username"])
            try:
                reports = research.list_owner(owner)
                server_research = getattr(self.state, "server_research", None)
                if server_research is not None:
                    published_report_ids = {
                        str(item.get("report_id") or "")
                        for item in reports
                        if isinstance(item, dict)
                    }
                    reports.extend(
                        item for item in server_research.list_owner(owner)
                        if str(item.get("report_id") or "") not in published_report_ids
                    )
                catalog_reports = {
                    str(item.get("report_id") or ""): item
                    for item in self.state.research_catalog.list_reports_for_scope(
                        viewer=owner, scope="mine",
                    )
                }
                for report in reports:
                    policy = catalog_reports.get(str(report.get("report_id") or ""))
                    if policy is None:
                        continue
                    report.update(
                        research_id=str(policy.get("research_id") or ""),
                        visibility=str(policy.get("visibility") or "private"),
                        authorized_users=list(policy.get("authorized_users") or []),
                    )
            except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 503)
                return True
            json_response(self, {
                "reports": reports,
            })
            return True
        return False
