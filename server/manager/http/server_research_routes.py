"""Authenticated server-Agent research report routes."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, unquote

from server.manager.http.responses import json_response


class ServerResearchRoutesMixin:
    """Read a server Profile's canonical report tree without a client mirror."""

    def _server_research_session(self):
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
        return session

    def _get_server_research_routes(self, parsed) -> bool:
        if not parsed.path.startswith("/api/server-research"):
            return False
        session = self._server_research_session()
        if session is None:
            return True
        principal = str(session.get("username") or "")
        service = self.state.server_research
        if parsed.path == "/api/server-research":
            try:
                value = service.list_owner(principal)
            except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 503)
                return True
            json_response(self, {"success": True, "research": value})
            return True

        component_match = re.fullmatch(
            r"/api/server-research/([^/]+)/chapters/([^/]+)/components/([^/]+)",
            parsed.path,
        )
        if component_match:
            try:
                value = service.component(
                    principal,
                    unquote(component_match.group(1)),
                    unquote(component_match.group(2)),
                    unquote(component_match.group(3)),
                )
                json_response(self, {"success": True, **value})
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
            except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
            return True

        chapter_match = re.fullmatch(
            r"/api/server-research/([^/]+)/(index|chapters/[^/]+)",
            parsed.path,
        )
        if chapter_match:
            try:
                server_ref = unquote(chapter_match.group(1))
                suffix = chapter_match.group(2)
                if suffix == "index":
                    value = service.index(principal, server_ref)
                else:
                    value = service.chapter(
                        principal,
                        server_ref,
                        unquote(suffix.split("/", 1)[1]),
                        include_content=parse_qs(parsed.query).get("metadata") != ["1"],
                    )
                json_response(self, {"success": True, **value})
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
            except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
            return True

        asset_match = re.fullmatch(
            r"/api/server-research/([^/]+)/assets/([a-f0-9]{24})",
            parsed.path,
        )
        if asset_match:
            try:
                raw, content_type, filename = service.asset(
                    principal,
                    unquote(asset_match.group(1)),
                    asset_match.group(2),
                    target_ref=parse_qs(parsed.query).get("target_ref", [""])[0]
                    or None,
                )
                self._send_server_research_bytes(
                    raw, content_type, filename, disposition="inline",
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
            except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
            return True

        resource_match = re.fullmatch(
            r"/api/server-research/([^/]+)/local-resources/([a-f0-9]{24})",
            parsed.path,
        )
        if resource_match:
            try:
                raw, content_type, filename = service.local_resource(
                    principal,
                    unquote(resource_match.group(1)),
                    resource_match.group(2),
                    target_ref=parse_qs(parsed.query).get("target_ref", [""])[0]
                    or None,
                )
                disposition = (
                    "inline" if parse_qs(parsed.query).get("inline") == ["1"]
                    else "attachment"
                )
                self._send_server_research_bytes(
                    raw, content_type, filename, disposition=disposition,
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
            except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
            return True

        report_match = re.fullmatch(
            r"/api/server-research/([^/]+)", parsed.path,
        )
        if report_match:
            try:
                value = service.projection(
                    principal, unquote(report_match.group(1)),
                )
                json_response(self, {"success": True, **value})
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
            except (OSError, ValueError, KeyError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
            return True
        if parsed.path == "/api/server-research/branch":
            query = parse_qs(parsed.query)
            try:
                value = service.read_branch(
                    principal,
                    target_ref=query.get("target_ref", [""])[0],
                    profile_id=query.get("profile_id", [""])[0],
                    package_id=query.get("package_id", [""])[0],
                    branch_id=query.get("branch_id", [""])[0],
                )
                json_response(self, {"success": True, **value})
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
            except (OSError, ValueError, KeyError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
            return True
        json_response(self, {"success": False, "error": "server research route not found"}, 404)
        return True

    def _send_server_research_bytes(
        self,
        raw: bytes,
        content_type: str,
        filename: str,
        *,
        disposition: str,
    ) -> None:
        safe_filename = re.sub(
            r"[^A-Za-z0-9._-]", "_", Path(filename).name,
        ) or "research-object"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header(
            "Content-Disposition",
            f'{disposition}; filename="{safe_filename}"',
        )
        self.send_header("Cache-Control", "private, no-cache")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


__all__ = ["ServerResearchRoutesMixin"]
