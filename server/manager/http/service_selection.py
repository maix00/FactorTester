"""Local/remote execution service authorization and route selection."""

from __future__ import annotations

import json
import re
import sys
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode

from server.manager.domain.federation import (
    ServiceRoute,
    TargetNotFound,
    TargetUnavailable,
)
from server.manager.http.gateway import GatewayResponse
from server.manager.http.responses import json_response
from server.manager.services.test_authoring import TestAuthoringError
from server.manager.services.factor_source_transfer import FactorSourceTransfer
from server.manager.services.factor_source_hydration import FactorSourceHydrator
from server.manager.storage.sqlite import ManagerSQLiteResponse
from server.services.research_run_context import MANAGER_RUN_CONTEXT_KEY


_SERVICE_GET_PREFIXES = (
    "/docs",
    "/static/css/",
    "/static/js/",
    "/static/vendor/",
    "/static/images/",
    "/custom-factors/api/client/factor-library",
    "/custom-factors/api/client/factor-sets",
    "/custom-factors/api/public-factor/",
    "/custom-factors/api/get/",
    "/api/product-groups",
    "/api/report-references/validate",
    "/api/profile-research",
    "/api/research-graphs/",
    "/api/research-evidence/",
    "/api/trial-plans/direct/",
    "/api/run-specs/",
    "/api/runs/",
    "/api/client/releases/",
    "/api/testers/modules",
)
_PUBLIC_GRAPH_READ_RE = re.compile(
    r"/api/research-graphs/[^/]+/(?:active|versions(?:/[0-9]+/(?:yaml|presentations))?)$"
)
_MAX_PREPARED_RUN_BODY_BYTES = 11 * 1024 * 1024


class ServiceSelectionRoutesMixin:
    """Resolve one capable service before any request is forwarded."""

    def _stage_factor_sources_for_route(
        self,
        route: ServiceRoute,
        *,
        principal: str,
    ) -> None:
        """Stage each factor object at most once per request and target."""
        target = str(route.server_id or "").strip()
        staged = getattr(self, "_staged_factor_source_targets", set())
        if target in staged:
            return
        FactorSourceTransfer(self.state).stage(
            getattr(self, "_prepared_factor_source_entries", ()),
            principal=principal,
            target_server_id=target,
        )
        staged.add(target)
        self._staged_factor_source_targets = staged

    def _has_manager_ui_session(self) -> bool:
        session = self.state.session(self._bearer_token())
        return bool(
            self._has_secure_ui_transport() and session
            and session["capabilities"]["manager"]
        )

    def _has_api_authorization(self) -> bool:
        return self._has_capability() or self._has_manager_ui_session()

    def _require_capability(self) -> bool:
        if self._has_capability():
            return True
        self.send_response(401)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("WWW-Authenticate", "Bearer")
        body = b'{"error":"manager capability required"}'
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def _job_ports(self, parsed, principal: str | None = None) -> list[int]:
        requested = parse_qs(parsed.query).get("port", [""])[0]
        indexed: list[int] = []
        if principal:
            match = re.fullmatch(
                r"/api/jobs/([A-Za-z0-9._-]{1,128})", parsed.path,
            )
            if match:
                indexed = self.state.job_index.ports_for(
                    principal, unquote(match.group(1)),
                )
        if requested.isdigit():
            port = int(requested)
            running = self.state.service_ports()
            # A cached job can outlive the service instance that created it.
            # Do not turn a stale/invalid port hint into a false 404; the
            # manager still owns the cross-port lookup and can find the job on
            # its currently running service.
            if port in running:
                return list(dict.fromkeys([*indexed, port]))
            return list(dict.fromkeys([*indexed, *running]))
        return list(dict.fromkeys([*indexed, *self.state.service_ports()]))

    def _service_port(self, parsed) -> int | None:
        requested = parse_qs(parsed.query).get("port", [""])[0]
        if requested.isdigit():
            value = int(requested)
            return value if value in self.state.service_ports() else None
        return self.state.preferred_service_port()

    def _service_route(self, parsed) -> ServiceRoute | None:
        query = parse_qs(parsed.query, keep_blank_values=True)
        raw_port = str(query.get("port", [""])[0] or "").strip()
        if raw_port and not raw_port.isdigit():
            json_response(
                self, {"success": False, "error": "port must be an integer"}, 400,
            )
            return None
        port = int(raw_port) if raw_port else None
        try:
            return self.state.route_for(
                port=port,
                server_id=str(query.get("server_id", [""])[0] or ""),
                branch=str(query.get("branch", [""])[0] or ""),
                feature=str(query.get("feature", [""])[0] or ""),
            )
        except TargetUnavailable as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
        except TargetNotFound as exc:
            json_response(self, {"success": False, "error": str(exc)}, 502)
        return None
    @staticmethod
    def _forwarded_service_path(parsed) -> str:
        manager_selector_keys = {"port", "server_id", "branch", "feature"}
        query = urlencode([
            (key, value) for key, value in parse_qsl(
                parsed.query, keep_blank_values=True,
            ) if key not in manager_selector_keys
        ])
        return parsed.path + (f"?{query}" if query else "")

    def _send_sqlite_web_response(self, response: ManagerSQLiteResponse) -> None:
        """Write a local sqlite-web WSGI response without a service-port header."""
        self.send_response(response.status)
        sent_content_length = False
        for key, value in response.headers:
            lowered = key.lower()
            if lowered in {"connection", "date", "server", "transfer-encoding"}:
                continue
            if lowered == "content-type":
                continue
            if lowered == "content-length":
                sent_content_length = True
                continue
            self.send_header(key, value)
        self.send_header("Content-Type", response.content_type)
        if not sent_content_length:
            self.send_header("Content-Length", str(len(response.body)))
        else:
            # The adapter materializes the response, so the actual length is
            # authoritative even if a middleware supplied a stale header.
            self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response.body)

    def _serve_sqlite_web(self, parsed, *, method: str) -> bool:
        """Serve `/sqlite-web` from Manager-owned state, never a worker port."""
        if not (
            parsed.path == "/sqlite-web"
            or parsed.path.startswith("/sqlite-web/")
        ):
            return False
        # The parent Manager route is a normal application tab.  Only the
        # embedded iframe (or a nested sqlite-web page reached from it) should
        # receive the database WSGI response; otherwise a browser refresh
        # would replace the Manager shell with raw sqlite-web HTML.
        if parsed.path in {"/sqlite-web", "/sqlite-web/"} and (
            parse_qs(parsed.query).get("presentation") != ["embedded"]
        ):
            return False
        session = self._session()
        # An embedded root without a Manager session must still render the
        # normal login shell.  Returning the JSON 401 body here makes a
        # WebView/tab show protocol data instead of the shared login UI.
        if session is None and parsed.path in {"/sqlite-web", "/sqlite-web/"}:
            return False
        if session is None:
            json_response(
                self, {"success": False, "error": "login required"}, 401,
            )
            return True
        body = b""
        if method in {"POST", "PUT", "PATCH"}:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except (TypeError, ValueError):
                json_response(
                    self, {"success": False, "error": "invalid request body"}, 400,
                )
                return True
            if length < 0 or length > 32 * 1024 * 1024:
                json_response(
                    self, {"success": False, "error": "invalid request body"}, 400,
                )
                return True
            body = self.rfile.read(length)
        try:
            response = self.state.sqlite_web.request(
                method=method,
                path=parsed.path,
                query=parsed.query,
                principal=str(session["username"]),
                headers={key: value for key, value in self.headers.items()},
                body=body,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            sys.stderr.write(f"[manager] sqlite-web failed: {exc}\n")
            json_response(
                self,
                {"success": False, "error": "manager database view unavailable"},
                503,
            )
            return True
        self._send_sqlite_web_response(response)
        return True

    def _proxy_service_get(self, parsed) -> bool:
        if not any(parsed.path.startswith(prefix) for prefix in _SERVICE_GET_PREFIXES):
            return False
        session = self._session()
        visitor = self._visitor_mode()
        if visitor is not None and not self._visitor_service_get_allowed(parsed.path):
            json_response(self, {
                "success": False,
                "error": "访客模式不能读取该服务端私有接口",
                "code": "visitor_private_service_read_forbidden",
            }, 403)
            return True
        public_graph = (
            session is None
            and visitor is None
            and _PUBLIC_GRAPH_READ_RE.fullmatch(parsed.path)
        )
        public_docs = (
            parsed.path == "/docs"
            or parsed.path.startswith("/docs/")
            or parsed.path.startswith("/static/css/")
            or parsed.path.startswith("/static/js/")
            or parsed.path.startswith("/static/vendor/")
            or parsed.path.startswith("/static/images/")
        )
        if session is None and visitor is None and not (public_graph or public_docs):
            json_response(
                self, {"success": False, "error": "login required"}, 401,
            )
            return True
        route = self._service_route(parsed)
        if route is None:
            return True
        try:
            response = self.state.route_request(
                route,
                path=self._forwarded_service_path(parsed),
                principal=(
                    visitor.principal if visitor is not None
                    else "__public_graph__" if public_graph
                    else "__public_docs__" if public_docs
                    else str(session["username"])
                ),
            )
        except (ConnectionError, ValueError):
            json_response(
                self, {"success": False, "error": "service port is unavailable"}, 502,
            )
            return True
        self._send_gateway_response(response, route=route)
        return True

    @staticmethod
    def _visitor_service_get_allowed(path: str) -> bool:
        """Keep visitor service reads limited to public test metadata.

        Catalogs, workspaces, schemas, and job reads are served by Manager
        routes.  A visitor only needs this service seam for the executable
        test-module manifest; allowing the broader authenticated prefix list
        here would expose private Profile/research/run-spec endpoints through
        the UUID-backed gateway session.
        """
        return path.startswith("/api/testers/modules")

    def _service_route_candidates(
        self, parsed,
    ) -> tuple[list[ServiceRoute], bool] | None:
        """Return online candidates while preserving explicit target intent."""
        query = parse_qs(parsed.query, keep_blank_values=True)
        raw_port = str(query.get("port", [""])[0] or "").strip()
        if raw_port and not raw_port.isdigit():
            json_response(
                self, {"success": False, "error": "port must be an integer"}, 400,
            )
            return None
        port = int(raw_port) if raw_port else None
        server_id = str(query.get("server_id", [""])[0] or "").strip()
        branch = str(query.get("branch", [""])[0] or "").strip()
        feature = str(query.get("feature", [""])[0] or "").strip()
        explicit = bool(server_id or raw_port or branch or feature)

        candidates = self.state.service_routes(include_offline=True)
        candidates = [
            route for route in candidates
            if (
                not server_id
                or server_id == "local" and not route.remote
                or route.server_id == server_id
            )
            and (port is None or route.port == port)
            and (not branch or route.branch == branch)
            and (not feature or feature in route.features)
        ]
        if not candidates:
            # Keep the legacy live-port seam used during bootstrap and in
            # tests where no Git worktree metadata is available.
            try:
                fallback = self.state.route_for(
                    port=port,
                    server_id=server_id,
                    branch=branch,
                    feature=feature,
                )
            except TargetUnavailable as exc:
                json_response(self, {"success": False, "error": str(exc)}, 503)
                return None
            except TargetNotFound as exc:
                json_response(self, {"success": False, "error": str(exc)}, 502)
                return None
            candidates = [fallback]

        online = [route for route in candidates if route.online]
        if not online:
            identity = server_id or branch or feature or (
                f"port {port}" if port is not None else "service target"
            )
            json_response(
                self,
                {"success": False, "error": f"target {identity} is offline"},
                503,
            )
            return None
        return sorted(online, key=self.state.route_selection_key), explicit

    @staticmethod
    def _gateway_json(response: GatewayResponse) -> dict[str, object]:
        try:
            value = response.json_object()
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _normalise_run_submission_identity(
        self,
        body: bytes,
        *,
        principal: str,
    ) -> bytes | None:
        """Validate and snapshot a locally owned Profile before forwarding."""
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            json_response(
                self,
                {"success": False, "error": "request body must be valid JSON"},
                400,
            )
            return None
        if not isinstance(value, dict):
            json_response(
                self,
                {"success": False, "error": "request body must be a JSON object"},
                400,
            )
            return None
        raw = str(value.get("acting_profile_ref") or "").strip()
        if not raw:
            # Preserve byte-for-byte forwarding for the ordinary user case;
            # existing API clients rely on this when signing request bodies.
            return body
        profile_id = raw.split(":", 1)[1] if raw.startswith("profile:") else raw
        profile_id = profile_id.strip()
        profiles = self.state.client_state.profiles(principal)
        selected = next(
            (
                item for item in profiles
                if str(item.get("profile_id") or "").strip() == profile_id
            ),
            None,
        )
        if selected is None:
            json_response(
                self,
                {
                    "success": False,
                    "error": "acting Profile does not belong to the current user",
                    "code": "acting_profile_not_owned",
                },
                403,
            )
            return None
        value["acting_profile_ref"] = f"profile:{profile_id}"
        value["acting_profile_name"] = str(
            selected.get("display_name") or profile_id
        ).strip()
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    def _prepare_manager_run_context(
        self,
        body: bytes,
        *,
        principal: str,
    ) -> bytes | None:
        """Replace any client-reserved value with origin-owned frozen state."""
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            json_response(
                self,
                {"success": False, "error": "request body must be valid JSON"},
                400,
            )
            return None
        if not isinstance(value, dict):
            json_response(
                self,
                {"success": False, "error": "request body must be a JSON object"},
                400,
            )
            return None
        value.pop(MANAGER_RUN_CONTEXT_KEY, None)
        source_entries: list[dict[str, object]] = []
        self._prepared_factor_source_entries = source_entries
        self._staged_factor_source_targets = set()
        try:
            context = self._prepare_run_context_with_sources(
                value, principal=principal, source_entries=source_entries,
            )
        except TestAuthoringError as exc:
            json_response(
                self,
                {"success": False, "error": str(exc), **exc.details},
                exc.status,
            )
            return None
        value[MANAGER_RUN_CONTEXT_KEY] = context
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        # The peer proxy Base64-encodes this body inside a 16 MiB JSON
        # envelope.  Eleven MiB leaves room for expansion and metadata.
        if len(encoded) > _MAX_PREPARED_RUN_BODY_BYTES:
            json_response(
                self,
                {"success": False, "error": "prepared run context is too large"},
                413,
            )
            return None
        return encoded

    def _prepare_run_context_with_sources(
        self,
        value: dict[str, object],
        *,
        principal: str,
        source_entries: list[dict[str, object]],
    ) -> dict[str, object]:
        """Hydrate only missing referenced sources, then freeze once more."""
        attempted: set[str] = set()
        while True:
            try:
                return self.state.test_authoring.prepare_run_context(
                    dict(value),
                    owner=principal,
                    source_free=True,
                    storage_server_id=self.state.server_id,
                    source_collector=source_entries.extend,
                )
            except TypeError as exc:
                if "unexpected keyword" not in str(exc):
                    raise
                return self.state.test_authoring.prepare_run_context(
                    dict(value), owner=principal,
                )
            except TestAuthoringError as exc:
                if str(exc.details.get("code") or "") != "factor_source_unavailable":
                    raise
                detail = str(exc.details.get("detail") or "")
                match = re.search(
                    r"Cannot load factor family source for ['\"]([^'\"]+)['\"]",
                    detail,
                )
                factor_ref = str(match.group(1) if match else "").strip()
                if not factor_ref or factor_ref in attempted:
                    raise
                attempted.add(factor_ref)
                if not FactorSourceHydrator(self.state).hydrate(
                    factor_ref, principal=principal,
                ):
                    raise

    def _capable_service_route(
        self,
        parsed,
        *,
        body: bytes,
        principal: str,
        content_type: str,
    ) -> ServiceRoute | None:
        """Select a route only after a read-only data-capability preflight."""
        candidates = self._service_route_candidates(parsed)
        if candidates is None:
            return None
        routes, explicit = candidates
        capability_failures: list[dict[str, object]] = []
        unavailable: list[dict[str, object]] = []
        requirements: list[dict[str, object]] = []
        for route in routes:
            try:
                self._stage_factor_sources_for_route(
                    route, principal=principal,
                )
                response = self.state.route_request(
                    route,
                    path="/api/runs/capability-preview",
                    principal=principal,
                    method="POST",
                    body=body,
                    content_type=content_type,
                )
            except (ConnectionError, OSError, RuntimeError, ValueError) as exc:
                unavailable.append({
                    "server_id": route.server_id,
                    "port": route.port,
                    "branch": route.branch,
                    "error": "service port is unavailable",
                    "detail": str(exc),
                })
                continue

            value = self._gateway_json(response)
            if 200 <= response.status < 300 and value.get("success", True):
                return route
            code = str(value.get("code") or "")
            if code == "data_capability_unavailable":
                candidate_requirements = value.get("requirements")
                if isinstance(candidate_requirements, list) and not requirements:
                    requirements = [
                        item for item in candidate_requirements
                        if isinstance(item, dict)
                    ]
                capability_failures.append({
                    "server_id": route.server_id,
                    "port": route.port,
                    "branch": route.branch,
                    "status": response.status,
                    "error": str(value.get("error") or "data capability unavailable"),
                })
                continue
            if response.status >= 500 or response.status == 404:
                unavailable.append({
                    "server_id": route.server_id,
                    "port": route.port,
                    "branch": route.branch,
                    "status": response.status,
                    "error": str(value.get("error") or "capability preflight unavailable"),
                })
                continue
            # The request itself is invalid (or the user is not authorised);
            # trying another server would only hide that client error.
            self._send_gateway_response(response, route=route)
            return None

        if capability_failures:
            json_response(self, {
                "success": False,
                "error": (
                    "no service target provides the requested "
                    "product, frequency, and data source"
                ),
                "code": "data_capability_unavailable",
                "requirements": requirements,
                "candidates": [*capability_failures, *unavailable],
                "explicit_target": explicit,
            }, 422)
            return None
        json_response(self, {
            "success": False,
            "error": "data capability preflight is unavailable",
            "code": "data_capability_preflight_unavailable",
            "candidates": unavailable,
            "explicit_target": explicit,
        }, 503)
        return None
