"""Authenticated client workspace and local research GET routes."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, unquote

from server.manager.http.responses import json_response


class ClientResearchRoutesMixin:
    """Expose owner-scoped local research and workspace projections."""

    def _get_client_research_routes(self, parsed) -> bool:
        if parsed.path == "/api/client/profiles":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            json_response(self, {
                "profiles": self.state.client_state.profiles(
                    str(session["username"]),
                ),
            })
            return True
        if parsed.path == "/api/client/workspace":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            json_response(self, {
                "workspace": self.state.client_state.workspace(
                    str(session["username"]),
                ),
            })
            return True
        if parsed.path == "/api/client/research":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            json_response(self, {
                "success": True,
                "research": self.state.client_state.local_research(
                    str(session["username"]),
                ),
            })
            return True
        local_research_resource_match = re.fullmatch(
            r"/api/client/research/([^/]+)/local-resources/([a-f0-9]{24})",
            parsed.path,
        )
        if local_research_resource_match:
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            try:
                raw, content_type, filename = self.state.client_state.local_research_resource(
                    str(session["username"]),
                    unquote(local_research_resource_match.group(1)),
                    local_research_resource_match.group(2),
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return True
            except (OSError, ValueError, KeyError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return True
            safe_filename = re.sub(
                r"[^A-Za-z0-9._-]", "_", Path(filename).name,
            ) or "resource"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            disposition = (
                "inline" if parse_qs(parsed.query).get("inline") == ["1"]
                else "attachment"
            )
            self.send_header(
                "Content-Disposition", f'{disposition}; filename="{safe_filename}"',
            )
            self.send_header("Cache-Control", "private, no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return True
        local_research_asset_match = re.fullmatch(
            r"/api/client/research/([^/]+)/assets/([a-f0-9]{24})",
            parsed.path,
        )
        if local_research_asset_match:
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            try:
                raw, content_type, filename = self.state.client_state.local_research_asset(
                    str(session["username"]),
                    unquote(local_research_asset_match.group(1)),
                    local_research_asset_match.group(2),
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return True
            except (OSError, ValueError, KeyError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return True
            safe_filename = re.sub(
                r"[^A-Za-z0-9._-]", "_", Path(filename).name,
            ) or "asset"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header(
                "Content-Disposition", f'inline; filename="{safe_filename}"',
            )
            self.send_header("Cache-Control", "private, no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return True
        local_research_component_match = re.fullmatch(
            r"/api/client/research/([^/]+)/chapters/([^/]+)/components/([^/]+)",
            parsed.path,
        )
        if local_research_component_match:
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            try:
                value = self.state.client_state.local_research_component(
                    str(session["username"]),
                    unquote(local_research_component_match.group(1)),
                    unquote(local_research_component_match.group(2)),
                    unquote(local_research_component_match.group(3)),
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return True
            except (OSError, ValueError, KeyError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return True
            json_response(self, {"success": True, **value})
            return True
        local_research_chapter_match = re.fullmatch(
            r"/api/client/research/([^/]+)/(index|chapters/[^/]+)", parsed.path,
        )
        if local_research_chapter_match:
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            local_ref = unquote(local_research_chapter_match.group(1))
            suffix = local_research_chapter_match.group(2)
            try:
                if suffix == "index":
                    value = self.state.client_state.local_research_index(
                        str(session["username"]), local_ref,
                    )
                else:
                    chapter_id = unquote(suffix.split("/", 1)[1])
                    value = self.state.client_state.local_research_chapter(
                        str(session["username"]), local_ref, chapter_id,
                        include_content=parse_qs(parsed.query).get("metadata") != ["1"],
                    )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return True
            except (OSError, ValueError, KeyError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return True
            json_response(self, {"success": True, **value})
            return True
        local_research_match = re.fullmatch(
            r"/api/client/research/([^/]+)", parsed.path,
        )
        if local_research_match:
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            try:
                value = self.state.client_state.local_research_report(
                    str(session["username"]),
                    unquote(local_research_match.group(1)),
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return True
            except (OSError, ValueError, KeyError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return True
            json_response(self, {"success": True, **value})
            return True
        if parsed.path == "/api/client/preferences":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            json_response(self, {
                "preferences": self.state.user_preferences.read(
                    str(session["username"]),
                ),
            })
            return True
        if self._serve_sqlite_web(parsed, method="GET"):
            return True
        if self._proxy_service_get(parsed):
            return True
        return False
