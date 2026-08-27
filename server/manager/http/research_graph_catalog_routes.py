"""Manager-owned HTTP routes for Research Graph catalogs and user files."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote

from server.manager.http.responses import json_response
from server.services.research_graph.protocol import GraphVersionConflict

GRAPH_CATALOG_PREFIX = "/api/catalog/research-graphs"
_VERSION_PATH = re.compile(
    rf"{re.escape(GRAPH_CATALOG_PREFIX)}/([^/]+)/versions$"
)
_ACTIVE_PATH = re.compile(
    rf"{re.escape(GRAPH_CATALOG_PREFIX)}/([^/]+)/active$"
)
_VERSION_DETAIL_PATH = re.compile(
    rf"{re.escape(GRAPH_CATALOG_PREFIX)}/([^/]+)/versions/(\d+)"
    rf"/(presentations|yaml|activate)$"
)
_USER_FILE_PATH = re.compile(
    rf"{re.escape(GRAPH_CATALOG_PREFIX)}/user-library/([^/]+)$"
)
_PUBLIC_CATALOG_READ_PATH = re.compile(
    rf"{re.escape(GRAPH_CATALOG_PREFIX)}/[^/]+/"
    r"(?:active|versions(?:/[0-9]+/(?:yaml|presentations))?)$"
)


def is_public_research_graph_catalog_read(path: str) -> bool:
    """Allow only immutable server Graph projections before login."""
    return _PUBLIC_CATALOG_READ_PATH.fullmatch(str(path or "")) is not None


class ResearchGraphCatalogRoutesMixin:
    """Keep Graph catalog reads/writes out of execution-port selection."""

    def _graph_catalog(self):
        return self.state.research_graph_catalog

    def _catalog_session(self) -> dict[str, object] | None:
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return None
        return session

    def _catalog_manager_session(self) -> dict[str, object] | None:
        session = self._catalog_session()
        if session is None:
            return None
        if str(session.get("role") or "") != "super_admin":
            json_response(
                self,
                {"success": False, "error": "super administrator required"},
                403,
            )
            return None
        return session

    def _catalog_read_principal(self, path: str) -> str | None:
        session = self._session()
        if session is not None:
            return str(session["username"])
        if self._visitor_mode() is not None:
            return "__public_graph__"
        if is_public_research_graph_catalog_read(path):
            return "__public_graph__"
        json_response(self, {"success": False, "error": "login required"}, 401)
        return None

    def _source_server_id(self, value: dict[str, object] | None) -> dict[str, object] | None:
        if value is None:
            return None
        return {
            **value,
            "source_server_id": self.state.server_id,
        }

    def _send_graph_yaml(self, body: bytes, filename: str, graph: dict, presentation: dict | None) -> None:
        response_etag = f'"{graph["content_hash"]}"'
        cache_control = "public, max-age=31536000, immutable"
        if presentation is not None:
            response_etag = (
                f'"{graph["graph_id"]}-v{int(graph["version"])}-'
                f'{presentation["locale"]}-{int(float(presentation["created_at"]) * 1000)}"'
            )
            cache_control = "no-cache"
        if self.headers.get("If-None-Match") == response_etag:
            self.send_response(304)
            self.send_header("ETag", response_etag)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/yaml")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", response_etag)
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-FactorTester-Graph-Version", str(graph["version"]))
        self.send_header("X-FactorTester-Graph-Content-Hash", str(graph["content_hash"]))
        if presentation is not None:
            self.send_header("Content-Language", str(presentation["locale"]))
            self.send_header("X-FactorTester-Graph-Locale", str(presentation["locale"]))
        self.end_headers()
        self.wfile.write(body)

    def _get_research_graph_catalog(self, parsed) -> bool:
        if not parsed.path.startswith(GRAPH_CATALOG_PREFIX):
            return False
        principal = self._catalog_read_principal(parsed.path)
        if principal is None:
            return True
        catalog = self._graph_catalog()
        query = parse_qs(parsed.query, keep_blank_values=True)
        locale = query.get("locale", [None])[0]
        try:
            if parsed.path == f"{GRAPH_CATALOG_PREFIX}/user-library":
                owner = self._catalog_session()
                if owner is None:
                    return True
                username = str(owner["username"])
                return self._write_json({
                    "success": True,
                    "files": catalog.list_user_graphs(username),
                    "default": self._source_server_id(
                        catalog.default_user_graph(username),
                    ),
                    "source_server_id": self.state.server_id,
                    "sync_scope": "manager-local",
                })
            if parsed.path == f"{GRAPH_CATALOG_PREFIX}/user-library/subordinates":
                owner = self._catalog_session()
                if owner is None:
                    return True
                from server.manager.domain.accounts import manager_subordinate_users

                files = []
                for account in manager_subordinate_users(str(owner["username"])):
                    username = str(account["username"])
                    for item in catalog.list_user_graphs(username):
                        files.append({
                            **item,
                            "owner_ref": username,
                            "owner_alias": account.get("alias") or "",
                            "source_server_id": self.state.server_id,
                        })
                return self._write_json({
                    "success": True,
                    "files": files,
                    "source_server_id": self.state.server_id,
                    "sync_scope": "manager-local",
                })
            if parsed.path == f"{GRAPH_CATALOG_PREFIX}/user-library/default":
                owner = self._catalog_session()
                if owner is None:
                    return True
                return self._write_json({
                    "success": True,
                    "default": self._source_server_id(
                        catalog.default_user_graph(str(owner["username"])),
                    ),
                    "source_server_id": self.state.server_id,
                    "sync_scope": "manager-local",
                })
            user_file = _USER_FILE_PATH.fullmatch(parsed.path)
            if user_file:
                owner = self._catalog_session()
                if owner is None:
                    return True
                username = str(owner["username"])
                requested_owner = str(query.get("owner", [username])[0] or username).strip()
                if requested_owner != username:
                    from server.manager.domain.accounts import manager_subordinate_users

                    allowed = {
                        str(item.get("username") or "").strip()
                        for item in manager_subordinate_users(username)
                    }
                    if requested_owner not in allowed:
                        return self._error_json("user research graph is not visible", 403)
                value = catalog.load_user_graph(
                    requested_owner, unquote(user_file.group(1)),
                )
                if value is None:
                    return self._error_json("user research graph not found", 404)
                if query.get("download", [""])[0].lower() in {"1", "true", "yes"}:
                    body = str(value["yaml"]).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/yaml")
                    self.send_header("Content-Disposition", f'attachment; filename="{value["filename"]}"')
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return True
                if query.get("view", [""])[0].lower() in {"1", "true", "yes"}:
                    value.pop("yaml", None)
                    return self._write_json({
                        "success": True,
                        "file": {**value, "owner_ref": requested_owner},
                    })
                value.pop("yaml", None)
                value.pop("graph", None)
                return self._write_json({
                    "success": True,
                    "file": {**value, "owner_ref": requested_owner},
                })
            version_match = _VERSION_PATH.fullmatch(parsed.path)
            if version_match:
                graph_id = unquote(version_match.group(1))
                return self._write_json({
                    "success": True,
                    "locale": locale,
                    "versions": catalog.list_versions(graph_id, locale=locale),
                })
            active_match = _ACTIVE_PATH.fullmatch(parsed.path)
            if active_match:
                graph = catalog.active_graph(
                    unquote(active_match.group(1)), locale=locale,
                )
                if graph is None:
                    return self._error_json("active graph not found", 404)
                return self._write_json({
                    "success": True,
                    "locale": locale,
                    "graph": graph,
                })
            detail_match = _VERSION_DETAIL_PATH.fullmatch(parsed.path)
            if detail_match:
                graph_id = unquote(detail_match.group(1))
                version = int(detail_match.group(2))
                operation = detail_match.group(3)
                if operation == "presentations":
                    graph = catalog.graph(graph_id, version)
                    if graph is None:
                        return self._error_json("graph version not found", 404)
                    return self._write_json({
                        "success": True,
                        "graph_id": graph_id,
                        "version": version,
                        "content_hash": graph["content_hash"],
                        "presentations": catalog.presentations(graph_id, version),
                    })
                if operation == "yaml":
                    body, filename, graph, presentation = catalog.yaml_download(
                        graph_id, version, locale=locale,
                    )
                    self._send_graph_yaml(body, filename, graph, presentation)
                    return True
                return self._error_json("unsupported catalog operation", 405)
            return self._error_json("research graph catalog route not found", 404)
        except KeyError as exc:
            return self._error_json(str(exc), 404)
        except LookupError as exc:
            return self._error_json(str(exc), 409)
        except ValueError as exc:
            return self._error_json(str(exc), 400)
        except (OSError, RuntimeError, TypeError) as exc:
            return self._error_json(str(exc), 503)

    def _post_research_graph_catalog(self, parsed) -> bool:
        if not parsed.path.startswith(GRAPH_CATALOG_PREFIX):
            return False
        catalog = self._graph_catalog()
        try:
            if parsed.path == f"{GRAPH_CATALOG_PREFIX}/versions":
                session = self._catalog_manager_session()
                if session is None:
                    return True
                payload = self._json_body(4 * 1024 * 1024)
                graph = payload.get("graph")
                if not isinstance(graph, dict):
                    raise ValueError("graph must be a JSON object")
                value = catalog.register_graph(
                    graph, actor=str(session["username"]),
                )
                return self._write_json({"success": True, "graph": value}, 201)
            if parsed.path.endswith("/activate"):
                match = _VERSION_DETAIL_PATH.fullmatch(parsed.path)
                if not match or match.group(3) != "activate":
                    return False
                session = self._catalog_manager_session()
                if session is None:
                    return True
                value = catalog.activate_graph(
                    unquote(match.group(1)), int(match.group(2)),
                    actor=str(session["username"]),
                )
                return self._write_json({"success": True, "graph": value}, 201)
            detail_match = _VERSION_DETAIL_PATH.fullmatch(parsed.path)
            if detail_match and detail_match.group(3) == "presentations":
                session = self._catalog_manager_session()
                if session is None:
                    return True
                payload = self._json_body(512 * 1024)
                presentation = payload.get("presentation", payload)
                if not isinstance(presentation, dict):
                    raise ValueError("presentation must be a JSON object")
                value = catalog.register_presentation(
                    unquote(detail_match.group(1)),
                    int(detail_match.group(2)),
                    presentation,
                    actor=str(session["username"]),
                )
                return self._write_json(
                    {"success": True, "presentation": value}, 201,
                )
            if parsed.path == f"{GRAPH_CATALOG_PREFIX}/user-library":
                session = self._catalog_session()
                if session is None:
                    return True
                payload = self._json_body(4 * 1024 * 1024)
                raw_yaml = payload.get("yaml")
                if not isinstance(raw_yaml, (str, bytes)):
                    raise ValueError("yaml must be text")
                value = catalog.upload_user_graph(
                    owner=str(session["username"]),
                    filename=str(payload.get("filename") or "research-graph.yaml"),
                    raw_yaml=raw_yaml,
                    name=str(payload.get("name") or ""),
                )
                value["source_server_id"] = self.state.server_id
                return self._write_json({
                    "success": True,
                    "file": value,
                    "sync_scope": "manager-local",
                }, 201)
            if parsed.path == f"{GRAPH_CATALOG_PREFIX}/user-library/default":
                session = self._catalog_session()
                if session is None:
                    return True
                payload = self._json_body(64 * 1024)
                value = catalog.set_default_user_graph(
                    owner=str(session["username"]),
                    kind=str(payload.get("kind") or "none"),
                    graph_file_id=str(payload.get("graph_file_id") or ""),
                    graph_id=str(payload.get("graph_id") or ""),
                    version=int(payload.get("version") or 0),
                )
                return self._write_json({
                    "success": True,
                    "default": self._source_server_id(value),
                    "source_server_id": self.state.server_id,
                    "sync_scope": "manager-local",
                })
            return False
        except GraphVersionConflict as exc:
            return self._error_json(str(exc), 409)
        except KeyError as exc:
            return self._error_json(str(exc), 404)
        except (TypeError, ValueError) as exc:
            return self._error_json(str(exc), 400)
        except (OSError, RuntimeError) as exc:
            return self._error_json(str(exc), 503)

    def _delete_research_graph_catalog(self, parsed) -> bool:
        if not parsed.path.startswith(GRAPH_CATALOG_PREFIX):
            return False
        match = _USER_FILE_PATH.fullmatch(parsed.path)
        if not match:
            return False
        try:
            session = self._catalog_session()
            if session is None:
                return True
            deleted = self._graph_catalog().delete_user_graph(
                str(session["username"]), unquote(match.group(1)),
            )
            if not deleted:
                return self._error_json("user research graph not found", 404)
            return self._write_json({"success": True, "deleted": unquote(match.group(1))})
        except (OSError, RuntimeError, ValueError) as exc:
            return self._error_json(str(exc), 503)

    def _write_json(self, payload: dict, status: int = 200) -> bool:
        json_response(self, payload, status)
        return True

    def _error_json(self, message: str, status: int) -> bool:
        json_response(self, {"success": False, "error": str(message)}, status)
        return True


__all__ = [
    "GRAPH_CATALOG_PREFIX",
    "ResearchGraphCatalogRoutesMixin",
    "is_public_research_graph_catalog_read",
]
