"""Public research projection, chapter, and attachment GET routes."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, unquote

from server.manager.http.responses import json_response


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
            json_response(self, {
                "reports": research.list_visible(viewer),
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
            except (ConnectionError, OSError) as exc:
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
            except (ConnectionError, OSError) as exc:
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
            except (ConnectionError, OSError) as exc:
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
            except (ConnectionError, OSError) as exc:
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
            except (ConnectionError, OSError) as exc:
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
            except (ConnectionError, OSError) as exc:
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
            json_response(self, {
                "reports": research.list_owner(
                    str(session["username"]),
                ),
            })
            return True
        return False
