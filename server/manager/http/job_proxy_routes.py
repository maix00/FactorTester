"""Execution writes, job reads, artifacts, and stream forwarding."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlencode
from urllib.request import Request, urlopen

from server.manager.http.content_encoding import (
    encode_body,
    encoding_headers,
    request_accept_encoding,
)
from server.manager.domain.federation import (
    ServiceRoute,
    TargetNotFound,
    TargetUnavailable,
)
from server.manager.http.gateway import GatewayResponse
from server.manager.http.job_public_projection import read_principals
from server.manager.http.responses import json_response
from server.manager.http.streaming import read_available

_SERVICE_WRITE_PATTERNS = {
    "POST": (
        r"/api/agent-flow/agents/[A-Za-z0-9._-]{1,256}/resume",
        r"/api/research-agent-executions",
        r"/api/runs/capability-preview",
        r"/api/runs(?:/preview)?",
        r"/api/jobs/[A-Za-z0-9._-]{1,128}/(?:approve|cancel|continue|retry)",
    ),
}
# Retention control scoped to the caller rather than a single job.  These
# paths carry no job id, so they are resolved before the per-job pattern.
_JOB_COLLECTION_DELETE_PATHS = frozenset({
    "/api/jobs",
    "/api/jobs/artifacts",
})
_JOB_ANALYSIS_PATHS = {
    "/group-detail": "/get_group_detail",
    "/group-ranking-detail": "/get_group_ranking_detail",
    "/group-snapshot": "/get_group_snapshot",
    "/group-order-flow": "/get_group_order_flow",
}
_PRODUCT_DATA_POST_PATHS = frozenset({
    "/api/data-availability",
    "/api/product-liquidity",
})


class JobProxyRoutesMixin:
    """Forward execution requests after selection and preserve provenance."""

    def _proxy_nautilus_preview(self, parsed, *, method: str) -> bool:
        """Forward only read-only Nautilus capability/configuration previews.

        Keep this allowlist separate from the broad execution proxy: the
        Nautilus namespace must not become an accidental live-order tunnel.
        """
        allowed = {
            ("GET", "/api/nautilus/capabilities"),
            ("POST", "/api/nautilus/config/preview"),
        }
        if (method, parsed.path) not in allowed:
            return False
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return True
        body = None
        if method == "POST":
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except (TypeError, ValueError):
                length = -1
            if length < 0 or length > 1024 * 1024:
                json_response(self, {"success": False, "error": "invalid request body"}, 400)
                return True
            body = self.rfile.read(length) if length else b""
        try:
            # This staged feature is local to the selected Manager's business
            # instance.  Explicit remote/unknown server IDs are not accepted.
            requested = str(parse_qs(parsed.query).get("server_id", [""])[0]).strip()
            if requested not in {"", "local", self.state.server_id}:
                json_response(self, {"success": False, "error": "local service required"}, 403)
                return True
            route = self._service_route(parsed)
            if route is None:
                return True
            if route.server_id != self.state.server_id:
                json_response(self, {
                    "success": False, "error": "local service required",
                }, 403)
                return True
            response = self.state.route_request(
                route, path=parsed.path,
                principal=str(session["username"]), method=method,
                body=body,
                content_type=str(self.headers.get("Content-Type") or "application/json"),
            )
        except (ConnectionError, OSError, RuntimeError, ValueError):
            json_response(self, {
                "success": False, "error": "business service is unavailable",
            }, 503)
            return True
        self._send_gateway_response(response, route=route)
        return True

    def _deferred_job_cleanup_route(self, parsed, *, method: str) -> bool:
        """Keep reversible offline deletion commands on the quota authority."""
        base = "/api/storage/deferred-job-cleanup"
        match = re.fullmatch(rf"{base}/([0-9a-f]{{32}})", parsed.path)
        if parsed.path != base and match is None:
            return False
        if (parsed.path == base and method not in {"GET", "POST"}) or (
            match is not None and method != "DELETE"
        ):
            json_response(self, {"success": False, "error": "method not allowed"}, 405)
            return True
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return True
        store = getattr(self.state, "control_store", None)
        if store is None:
            json_response(self, {"success": False,
                                 "error": "quota authority unavailable"}, 503)
            return True
        principal = str(session["username"])
        try:
            if method == "GET":
                value = {"requests": store.deferred_output_cleanups(principal)}
            elif method == "POST":
                body = self._json_body(4096)
                if not isinstance(body, dict):
                    raise ValueError("cleanup request must be an object")
                value = store.queue_deferred_output_cleanup(
                    principal=principal,
                    server_id=str(body.get("server_id") or ""),
                    expected_bytes=int(body.get("expected_bytes") or 0),
                    expected_count=int(body.get("expected_count") or 0),
                    observed_at=str(body.get("observed_at") or ""),
                )
            else:
                value = store.cancel_deferred_output_cleanup(
                    principal=principal, request_id=match.group(1),
                )
        except (TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 409)
            return True
        except Exception:
            json_response(self, {"success": False,
                                 "error": "quota authority unavailable"}, 503)
            return True
        json_response(self, {"success": True, **value},
                      headers={"Cache-Control": "private, no-store"})
        return True

    def _with_local_service_selector(self, parsed):
        """Bind unqualified service-port hints to this Manager's server."""
        query = parse_qs(parsed.query, keep_blank_values=True)
        if str(query.get("server_id", [""])[0] or "").strip():
            return parsed
        query["server_id"] = [str(self.state.server_id)]
        encoded = urlencode([
            (key, value)
            for key, values in query.items()
            for value in values
        ])
        return parsed._replace(query=encoded)

    def _proxy_selected_job_list(self, parsed) -> bool:
        """Route an explicitly selected job-list service through Manager."""
        if parsed.path != "/api/jobs":
            return False
        query = parse_qs(parsed.query, keep_blank_values=True)
        raw_port = str(query.get("port", [""])[0] or "").strip()
        if not raw_port or raw_port.lower() == "all":
            return False
        if not raw_port.isdigit():
            json_response(self, {
                "success": False,
                "error": "port must be an integer or all",
            }, 400)
            return True
        raw_server = str(query.get("server_id", [""])[0] or "").strip()
        if raw_server in {"", "local", self.state.server_id}:
            if int(raw_port) not in self.state.service_ports():
                json_response(self, {
                    "success": False,
                    "error": "port is not an active service published by this server",
                }, 400)
                return True

        session = self._session()
        visitor = self._visitor_mode()
        principal = (
            str(session["username"])
            if session is not None
            else (
                visitor.principal if visitor is not None
                else "__public_jobs__"
            )
        )
        route = self._service_route(self._with_local_service_selector(parsed))
        if route is None:
            return True

        forwarded_path = self._forwarded_service_path(parsed)
        if not str(query.get("scope", [""])[0] or "").strip():
            scope = (
                "server"
                if session is None or str(session.get("role") or "") == "super_admin"
                else "mine"
            )
            forwarded_path += "&" if "?" in forwarded_path else "?"
            forwarded_path += f"scope={scope}"
        try:
            response = self.state.route_request(
                route,
                path=forwarded_path,
                principal=principal,
                method="GET",
                content_type="application/json",
            )
        except (ConnectionError, OSError, RuntimeError, ValueError):
            json_response(self, {
                "success": False,
                "error": "selected job service is unavailable",
                "code": "selected_job_service_unavailable",
            }, 503)
            return True
        self._send_gateway_response(response, route=route)
        return True

    def _proxy_product_data_service(self, parsed, *, method: str) -> bool:
        """Forward the small public data API surface through Manager routing."""
        supported = (
            method == "GET"
            and (
                parsed.path == "/api/data-capabilities"
                or re.fullmatch(
                    r"/api/data-availability/profiles/[^/]{1,1024}",
                    parsed.path,
                ) is not None
            )
        ) or (method == "POST" and parsed.path in _PRODUCT_DATA_POST_PATHS)
        if not supported:
            return False

        session = self._session()
        if session is None:
            json_response(
                self, {"success": False, "error": "login required"}, 401,
            )
            return True

        query = parse_qs(parsed.query, keep_blank_values=True)
        raw_port = str(query.get("port", [""])[0] or "").strip()
        raw_server = str(query.get("server_id", [""])[0] or "").strip()
        if raw_port and not raw_port.isdigit():
            json_response(self, {
                "success": False,
                "error": "port must be an integer",
            }, 400)
            return True
        if raw_port and raw_server in {"", "local", self.state.server_id}:
            if int(raw_port) not in self.state.service_ports():
                json_response(self, {
                    "success": False,
                    "error": "port is not an active service published by this server",
                }, 400)
                return True

        route = self._service_route(self._with_local_service_selector(parsed))
        if route is None:
            return True

        body = None
        content_type = str(
            self.headers.get("Content-Type") or "application/json"
        )
        if method != "GET":
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except (TypeError, ValueError):
                length = -1
            if length < 0 or length > 1024 * 1024:
                json_response(
                    self,
                    {"success": False, "error": "invalid request body"},
                    400,
                )
                return True
            body = self.rfile.read(length) if length else b""

        try:
            response = self.state.route_request(
                route,
                path=self._forwarded_service_path(parsed),
                principal=str(session["username"]),
                method=method,
                body=body,
                content_type=content_type,
            )
        except (ConnectionError, OSError, RuntimeError, ValueError):
            json_response(self, {
                "success": False,
                "error": "business data service is unavailable",
                "code": "business_data_service_unavailable",
            }, 503)
            return True
        self._send_gateway_response(response, route=route)
        return True

    def _proxy_authenticated_local_service(self, parsed, *, method: str) -> bool:
        """Bridge canonical Manager namespaces to one authenticated service."""
        namespaces = (
            (
                "/api/factor-library/",
                "/api/internal/factor-library/",
                {
                    "families/operators": "operators",
                    "families/validate": "validate",
                    "families/formula-preview": "formula-preview",
                    "families/custom": "families/custom",
                    "families/public": "families/public",
                },
            ),
            ("/api/admin/", "/admin/api/", {}),
        )
        selected = next(
            (item for item in namespaces if parsed.path.startswith(item[0])),
            None,
        )
        if selected is None:
            return False
        prefix, internal_prefix, aliases = selected
        query_values = parse_qs(parsed.query, keep_blank_values=True)
        requested_server = str(
            query_values.get("server_id", [""])[0] or ""
        ).strip()
        if (
            self._is_local_agent_request()
            and requested_server not in {"", "local", self.state.server_id}
        ):
            json_response(self, {
                "success": False,
                "error": "Profile Agent service requests must stay local",
                "code": "agent_service_target_must_be_local",
            }, 403)
            return True
        session = self._session()
        if session is None:
            json_response(
                self, {"success": False, "error": "login required"}, 401,
            )
            return True
        suffix = parsed.path.removeprefix(prefix)
        if prefix == "/api/factor-library/" and not any(
            re.fullmatch(pattern, suffix)
            for pattern in (
                r"overview",
                r"families/(?:operators|validate|formula-preview|custom|public)",
                r"families/(?:custom|public)/[^/]+(?:/(?:impact|transfer))?",
                r"configurations/[^/]+(?:/[^/]+|/factors)?",
                r"configuration-scopes(?:/[^/]+)?",
                r"workspace/user/(?:root|download|upload|merge-download)",
            )
        ):
            return False
        workspace_push = (
            method == "POST" and suffix == "workspace/user/upload"
        )
        if workspace_push and str(session.get("role") or "") != "super_admin":
            json_response(self, {
                "success": False,
                "error": "super administrator permission required",
            }, 403)
            return True
        internal_suffix = aliases.get(suffix, suffix)
        internal_path = internal_prefix + internal_suffix
        forwarded_query = urlencode([
            (key, value)
            for key, values in query_values.items()
            if key not in {"server_id", "port", "branch", "feature"}
            for value in values
        ])
        if forwarded_query:
            internal_path += f"?{forwarded_query}"
        body = None
        content_type = str(
            self.headers.get("Content-Type") or "application/json"
        )
        if method != "GET":
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 1024 * 1024:
                json_response(
                    self,
                    {"success": False, "error": "invalid request body"},
                    400,
                )
                return True
            body = self.rfile.read(length) if length else b""
        try:
            changing_family = re.fullmatch(r'families/(custom|public)/([^/]+)/(impact|transfer)', suffix)
            if changing_family:
                if changing_family.group(1) == 'public' or changing_family.group(3) == 'transfer':
                    if session.get('role') != 'super_admin':
                        raise PermissionError('需要超级管理员权限')
                sync = getattr(getattr(self.state, 'client_state', None), 'account_domain_sync', None)
                if sync is not None:
                    store = getattr(self.state.client_state, 'local_account_store', None)
                    accounts = store.load_accounts() if store is not None else []
                    principals = {str(session['username']), '__public__'}
                    if changing_family.group(1) == 'public':
                        principals.update(str(row['username']) for row in accounts if row.get('username'))
                    for user in sorted(principals):
                        for _ in range(100):
                            state = sync.pull(principal=user, limit=1000)
                            if state.get('offline') or state.get('conflicts'):
                                raise RuntimeError('无法确认完整依赖，请先恢复同步或解决冲突')
                            if not state.get('has_more'):
                                break
                        else:
                            raise RuntimeError('依赖尚未同步完整，请稍后重试')
                from server.manager.services.factor_family_current import ensure_current_family
                if not ensure_current_family(self.state, changing_family.group(1), unquote(changing_family.group(2)),
                    principal=str(session['username'])):
                    raise ValueError('家族已删除或源码尚不可用')
            family_match = re.fullmatch(r'families/(custom|public)/([^/]+)', suffix)
            if prefix == '/api/factor-library/' and family_match and method in {'GET', 'PUT', 'DELETE'}:
                from server.manager.services.factor_family_current import ensure_current_family
                if not ensure_current_family(
                    self.state, family_match.group(1), unquote(family_match.group(2)),
                    principal=str(session['username']),
                    owner=str(query_values.get('owner_username', [''])[0]) if method == 'GET' else '',
                ) and method != 'DELETE':
                    # A retry must reach the delete route to clear residual
                    # mirrored registrations after the family head was deleted.
                    json_response(self, {'success': False, 'error': '因子家族已删除或源码尚不可用'}, 404)
                    return True
            route = self.state.route_for(server_id=self.state.server_id)
            response = self.state.route_request(
                route,
                path=internal_path,
                principal=str(session["username"]),
                method=method,
                body=body,
                content_type=content_type,
            )
        except PermissionError as error:
            json_response(self, {'success': False, 'error': str(error)}, 403)
            return True
        except (ConnectionError, RuntimeError, ValueError):
            json_response(
                self,
                {"success": False, "error": "local service is unavailable"},
                502,
            )
            return True
        if method != "GET" and suffix != "families/formula-preview" and 200 <= response.status < 300:
            refresh = getattr(getattr(self.state, "client_state", None), "_refresh_account_domain_async", None)
            if callable(refresh) and response.json_object().get("success", True):
                refresh(str(session["username"]), force=True)
                for owner in response.json_object().get('affected_users', []):
                    if owner != str(session['username']):
                        refresh(owner, force=True)
        if workspace_push and 200 <= response.status < 300:
            try:
                value = response.json_object()
                changes = value.get("public_factor_changes") or []
                if changes:
                    value["public_factor_replication"] = (
                        self.state.public_factor_replication.publish(
                            changes, principal=str(session["username"]),
                        )
                    )
                    response = GatewayResponse(
                        status=response.status,
                        body=json.dumps(value, ensure_ascii=False).encode("utf-8"),
                        content_type="application/json",
                        content_disposition=response.content_disposition,
                        etag=response.etag,
                    )
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                json_response(self, {
                    "success": False,
                    "error": str(exc),
                    "code": "public_factor_replication_failed",
                }, 503)
                return True
        self._send_gateway_response(response, route=route)
        return True

    @staticmethod
    def _safe_local_service_suffix(suffix: str) -> bool:
        """Accept resource paths, never traversal or an arbitrary URL."""
        value = unquote(str(suffix or "")).strip("/")
        if not value:
            return True
        segments = value.split("/")
        return all(
            segment not in {"", ".", ".."}
            and re.fullmatch(r"[A-Za-z0-9._:@+%-]{1,256}", segment)
            for segment in segments
        )

    def _proxy_service_write(self, parsed, *, method: str) -> bool:
        patterns = _SERVICE_WRITE_PATTERNS.get(method, ())
        registered_route = any(
            re.fullmatch(pattern, parsed.path) for pattern in patterns
        )
        if not registered_route:
            return False
        session = self._session()
        visitor = self._visitor_mode()
        visitor_submission = session is None and visitor is not None
        if session is None and not visitor_submission:
            json_response(
                self, {"success": False, "error": "login required"}, 401,
            )
            return True
        if visitor_submission and parsed.path not in {
            "/api/runs", "/api/runs/preview", "/api/runs/capability-preview",
        }:
            json_response(self, {
                "success": False,
                "error": "访客模式只能提交公开因子和产品测试",
                "code": "visitor_service_write_forbidden",
            }, 403)
            return True
        principal = (
            visitor.principal
            if visitor_submission and visitor is not None
            else str(session["username"])
        )
        workspace_push = False
        if workspace_push and str(session.get("role") or "") != "super_admin":
            json_response(self, {
                "success": False,
                "error": "super administrator permission required",
            }, 403)
            return True
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1024 * 1024:
            json_response(
                self, {"success": False, "error": "invalid request body"}, 400,
            )
            return True
        body = self.rfile.read(length)
        content_type = str(self.headers.get("Content-Type") or "application/json")
        run_request = method == "POST" and parsed.path in {
            "/api/runs", "/api/runs/preview", "/api/runs/capability-preview",
        }
        if run_request:
            if visitor_submission and not self._visitor_run_body_allowed(body):
                return True
            body = self._normalise_run_submission_identity(
                body, principal=principal,
            )
            if body is None:
                return True
            body = self._prepare_manager_run_context(
                body, principal=principal,
            )
            if body is None:
                return True
        if method == "POST" and parsed.path == "/api/runs":
            route = self._capable_service_route(
                parsed,
                body=body,
                principal=principal,
                content_type=content_type,
            )
        else:
            route = self._service_route(parsed)
        if route is None:
            return True
        if workspace_push and route.server_id != self.state.server_id:
            json_response(self, {
                "success": False,
                "error": "factor workspace push must use its local Manager",
            }, 409)
            return True
        try:
            if run_request:
                self._stage_factor_sources_for_route(
                    route,
                    principal=principal,
                )
            response = self.state.route_request(
                route,
                path=self._forwarded_service_path(parsed),
                principal=principal,
                method=method,
                body=body,
                content_type=content_type,
                origin_server_id=(
                    self.state.server_id
                    if method == "POST" and parsed.path == "/api/runs"
                    else ""
                ),
            )
        except (ConnectionError, RuntimeError, ValueError):
            json_response(
                self, {"success": False, "error": "service port is unavailable"}, 502,
            )
            return True
        if method == "POST" and parsed.path == "/api/runs":
            self.state.record_run_submission(
                response,
                principal=principal,
                route=route,
                origin_server_id=self.state.server_id,
            )
        if workspace_push and 200 <= response.status < 300:
            try:
                value = response.json_object()
                changes = value.get("public_factor_changes") or []
                if changes:
                    value["public_factor_replication"] = (
                        self.state.public_factor_replication.publish(
                            changes, principal=principal,
                        )
                    )
                    response = GatewayResponse(
                        status=response.status,
                        body=json.dumps(value, ensure_ascii=False).encode("utf-8"),
                        content_type="application/json",
                        content_disposition=response.content_disposition,
                        etag=response.etag,
                    )
            except (ConnectionError, OSError, RuntimeError, TypeError, ValueError) as exc:
                json_response(self, {
                    "success": False,
                    "error": str(exc),
                    "code": "public_factor_replication_failed",
                }, 503)
                return True
        self._send_gateway_response(
            response,
            route=route,
            include_route_identity=parsed.path in {"/api/runs", "/api/runs/preview"},
        )
        return True

    def _visitor_run_body_allowed(self, body: bytes) -> bool:
        """Reject executable/private source injection from visitor runs."""
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            # The normal JSON validation below returns the more precise error.
            return True
        if not isinstance(value, dict):
            return True
        forbidden = {
            "transient_factor_sources",
            "transient_strategy_sources",
            "portable_factor_sources",
        }
        if any(value.get(key) for key in forbidden):
            json_response(self, {
                "success": False,
                "error": "访客模式只能运行服务器公开因子和产品，不能提交源码",
                "code": "visitor_source_submission_forbidden",
            }, 403)
            return False
        strategy_specs = value.get("strategy_specs")
        if isinstance(strategy_specs, list) and any(
            isinstance(item, dict) and (
                item.get("source_code")
                or item.get("source_path")
                or item.get("local_path")
            )
            for item in strategy_specs
        ):
            json_response(self, {
                "success": False,
                "error": "访客模式不能提交策略源码",
                "code": "visitor_strategy_source_forbidden",
            }, 403)
            return False
        return True
    def _send_gateway_response(
        self,
        response: GatewayResponse,
        *,
        port: int | None = None,
        route: ServiceRoute | None = None,
        include_route_identity: bool = False,
    ) -> None:
        selected_port = int(route.port if route is not None else (port or 0))
        body = response.body
        content_type = response.content_type
        if content_type == "application/json":
            try:
                value = response.json_object()
                value.setdefault("port", selected_port)
                # The service response is intentionally unchanged at the
                # execution layer, but the Manager must tell the browser
                # which federated node answered.  Artifact reads use this
                # server identity only; their data-plane route is 7997 and
                # must never inherit the test worker's execution port.
                if include_route_identity and route is not None:
                    value.setdefault("server_id", route.server_id)
                    value.setdefault("execution_server_id", route.server_id)
                    value.setdefault("execution_port", selected_port)
                    value.setdefault("storage_server_id", route.server_id)
                body = json.dumps(value, ensure_ascii=False).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
                pass
        # The business service is reached through this bridge; compress here so
        # a large catalog projection travels once, compressed, over the public
        # uplink instead of as raw JSON.
        body, encoded = encode_body(
            body, content_type, request_accept_encoding(self),
        )
        self.send_response(response.status)
        self.send_header("Content-Type", content_type)
        if response.content_disposition:
            self.send_header(
                "Content-Disposition", response.content_disposition,
            )
        if response.etag:
            self.send_header("ETag", response.etag)
        self.send_header("X-FactorTester-Service-Port", str(selected_port))
        if route is not None:
            self.send_header("X-FactorTester-Service-Server", route.server_id)
            if route.branch:
                self.send_header("X-FactorTester-Service-Branch", route.branch)
        for key, value in encoding_headers(encoded).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _index_job_detail_response(
        self, response: GatewayResponse, *, route: ServiceRoute, principal: str,
    ) -> None:
        """Remember routing exposed by a permitted detail read.

        A copied Job URL can be opened immediately after Manager restart,
        before a task-list request has rebuilt the local routing index.
        Artifact lookup still needs the Job owner and storage server, so seed
        the same bounded index from the already-authorized detail response.
        """
        if response.status != 200 or response.content_type != "application/json":
            return
        try:
            payload = response.json_object()
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return
        detail = payload.get("task_detail") if isinstance(payload, dict) else None
        job = detail.get("job") if isinstance(detail, dict) else None
        source = job if isinstance(job, dict) else payload
        if not isinstance(source, dict):
            return
        job_id = str(source.get("job_id") or payload.get("job_id") or "").strip()
        if not job_id:
            return
        indexed = {
            **source,
            "job_id": job_id,
            "port": int(source.get("port") or route.port),
            "owner": str(source.get("owner") or payload.get("owner") or principal),
            "server_id": str(payload.get("server_id") or route.server_id),
            "execution_server_id": str(
                payload.get("execution_server_id") or route.server_id
            ),
            "storage_server_id": str(
                payload.get("storage_server_id") or route.server_id
            ),
        }
        for owner in {principal, str(indexed["owner"]), "__public_jobs__"}:
            if owner:
                self.state.job_index.upsert(owner, [indexed], emit_events=False)

    def _job_routes(
        self,
        parsed,
        principal: str | None = None,
        *,
        for_artifact_storage: bool = False,
    ) -> list[ServiceRoute]:
        """Resolve execution or storage origins for a Job request.

        A Job's execution identity is ``server_id + port``.  Retained
        artifacts have a different identity: ``storage_server_id``.  The
        latter is deliberately resolved at server scope, so a stopped
        worktree port cannot make an otherwise retained artifact unavailable.
        """
        query = parse_qs(parsed.query, keep_blank_values=True)
        raw_port = str(query.get("port", [""])[0] or "").strip()
        if raw_port and not raw_port.isdigit():
            raise ValueError("port must be an integer")
        port = int(raw_port) if raw_port and not for_artifact_storage else None
        server_id = str(query.get("server_id", [""])[0] or "").strip()
        if for_artifact_storage and not server_id:
            job_match = re.match(r"^/api/jobs/([^/]+)", parsed.path)
            indexed = self._indexed_storage_servers(
                unquote(job_match.group(1)) if job_match is not None else "",
            )
            if len(indexed) == 1:
                server_id = next(iter(indexed))
        branch = (
            str(query.get("branch", [""])[0] or "").strip()
            if not for_artifact_storage else ""
        )
        feature = (
            str(query.get("feature", [""])[0] or "").strip()
            if not for_artifact_storage else ""
        )
        if for_artifact_storage:
            routes = self.state.service_routes(include_offline=True)
            if server_id:
                routes = [item for item in routes if item.server_id == server_id]
            if routes:
                # The worker port may be stopped. Artifact control requests
                # use only this source Manager identity and endpoint.
                return sorted(routes, key=self.state.route_selection_key)
            if not routes:
                # Keep the lightweight Manager/unit-test seam where a caller
                # supplies a route resolver without populating the registry.
                # The resolver still receives no execution-port constraint.
                if not server_id:
                    legacy_ports = self._job_ports(parsed, principal)
                    if legacy_ports:
                        return [
                            self.state._local_route(port=value, online=True)
                            for value in legacy_ports
                        ]
                if server_id in {self.state.server_id, "local"}:
                    running_ports = list(self.state.service_ports())
                    if running_ports:
                        return [
                            self.state._local_route(port=value, online=True)
                            for value in running_ports
                        ]
                    # Metadata belongs to this Manager's storage repository;
                    # the zero-port route is only a control-plane identity.
                    # It deliberately does not imply that a business service
                    # is running or that artifact bytes should use a worker
                    # port.
                    return [self.state._local_route(port=0, online=True)]
                descriptor = self.state.federation_registry.describe(server_id)
                if descriptor is not None:
                    transfer_node = descriptor.get("transfer_node")
                    transfer_node = (
                        transfer_node if isinstance(transfer_node, dict) else {}
                    )
                    return [ServiceRoute(
                        server_id=server_id,
                        role=str(descriptor.get("role") or ""),
                        branch=str(descriptor.get("branch") or ""),
                        revision=str(descriptor.get("revision") or ""),
                        port=0,
                        endpoint=str(descriptor.get("endpoint") or ""),
                        peer_control_endpoint=str(
                            transfer_node.get("peer_control_endpoint") or ""
                        ).rstrip("/"),
                        peer_data_endpoint=str(
                            transfer_node.get("peer_data_endpoint") or ""
                        ).rstrip("/"),
                        proxy_token=str(descriptor.get("proxy_token") or ""),
                        remote=True,
                        online=bool(descriptor.get("online", True)),
                        public_server=bool(descriptor.get("public_server")),
                    )]
                fallback = self.state.route_for(server_id=server_id)
                return [fallback]
        explicit = bool(server_id or branch or feature or port is not None)
        has_peers = bool(
            self.state.federation_registry.servers(include_offline=True)
        )
        if explicit:
            return [self.state.route_for(
                port=port,
                server_id=server_id,
                branch=branch,
                feature=feature,
            )]
        if has_peers:
            routes = self.state.service_routes(include_offline=True)
            # An unqualified request is allowed to select any currently
            # online candidate.  An unrelated stopped peer is not a reason
            # to reject a local/public target: retained result data and
            # storage-backed supplemental analysis may be entirely owned by
            # the online Manager.  An explicit ``server_id``/port still goes
            # through ``route_for`` above and therefore keeps its precise
            # offline-target error.
            online = [route for route in routes if route.online]
            if not online:
                raise TargetUnavailable("no online service target")
            return sorted(online, key=self.state.route_selection_key)
        # Preserve the legacy manager test seam and local cached origins when
        # no peer Manager has been registered yet.
        return [
            self.state._local_route(port=value, online=True)
            for value in self._job_ports(parsed, principal)
        ]

    def _indexed_storage_servers(self, job_id: str) -> set[str]:
        """Resolve an artifact's server from the Manager index, never a port."""
        target = str(job_id or "").strip()
        index = getattr(self.state, "job_index", None)
        if not target or index is None:
            return set()
        try:
            jobs = index.list_all(limit=2000)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            return set()
        return {
            str(
                item.get("storage_server_id")
                or item.get("execution_server_id")
                or item.get("server_id")
                or ""
            ).strip()
            for item in jobs
            if isinstance(item, dict)
            and str(item.get("job_id") or "").strip() == target
            and str(
                item.get("storage_server_id")
                or item.get("execution_server_id")
                or item.get("server_id")
                or ""
            ).strip()
        }

    def _proxy_job_request(self, parsed, *, method: str) -> bool:
        if self._proxy_job_collection_request(parsed, method=method):
            return True
        match = re.fullmatch(
            r"/api/jobs/([A-Za-z0-9._-]{1,128})"
            r"(/result|/artifacts(?:/[A-Za-z0-9._%+-]{1,512})?"
            r"|/supplementals(?:/[A-Za-z0-9._-]{1,128})?"
            r"|/custom-analyses(?:/[A-Za-z0-9._-]{1,128})?"
            r"|/group-detail|/group-ranking-detail|/group-snapshot"
            r"|/group-order-flow)?",
            parsed.path,
        )
        if match is None:
            return False
        suffix = match.group(2) or ""
        # Retained artifact bytes are served only through the short-lived
        # Manager-issued ``/access`` capability.  The old direct byte routes
        # must remain an unconditional 404 (including for anonymous callers)
        # instead of falling through to a worker-port proxy or an auth 401.
        if method == "GET" and suffix.startswith("/artifacts/"):
            return False
        supplemental_collection = suffix == "/supplementals"
        custom_analysis_collection = suffix == "/custom-analyses"
        custom_analysis_item = suffix.startswith("/custom-analyses/")
        if method == "POST" and not (
            suffix in _JOB_ANALYSIS_PATHS
            or supplemental_collection
            or custom_analysis_collection
        ):
            return False
        if method == "PATCH" and not custom_analysis_item:
            return False
        if method == "DELETE" and not (
            suffix == "/artifacts" or suffix.startswith("/artifacts/")
            or custom_analysis_item
        ):
            return False
        session = self._session()
        visitor = self._visitor_mode()
        suffix_value = suffix
        public = (
            session is None
            and method == "GET"
            and (
                suffix_value in {"", "/result", "/artifacts"}
                or suffix_value.startswith("/supplementals")
                or suffix_value == "/custom-analyses"
            )
        )
        if session is None and not public:
            json_response(
                self, {"success": False, "error": "login required"}, 401,
            )
            return True
        if public:
            principal = (
                visitor.principal if visitor is not None else "__public_jobs__"
            )
        else:
            principal = str(session["username"])
        job_id = quote(unquote(match.group(1)), safe="")
        local_projection = getattr(self.state, "local_run_projection", None)
        local_run = None
        if local_projection is not None and session is not None:
            local_run = local_projection.get(
                principal, unquote(match.group(1)),
            )
        if local_run is not None:
            if method != "GET":
                json_response(self, {
                    "success": False,
                    "error": "本地运行任务只能在客户端本地控制",
                    "code": "local_run_read_only",
                }, 409)
                return True
            if suffix_value == "":
                json_response(self, {
                    "success": True,
                    "task_detail": local_run["task_detail"],
                    "result_summary": local_run["result_summary"],
                    "execution_mode": "local",
                    "local_run": True,
                    "raw_artifacts_remote": local_run["raw_artifacts_remote"],
                    "port": 0,
                })
                return True
            if suffix_value == "/result":
                json_response(self, {
                    "success": True,
                    "result": local_run["result_summary"],
                    "result_summary": local_run["result_summary"],
                    "local_run": True,
                })
                return True
            if suffix_value == "/artifacts":
                json_response(self, {
                    "success": True,
                    "artifacts": local_run["task_detail"].get("artifacts") or [],
                    "raw_artifacts_remote": local_run["raw_artifacts_remote"],
                    "local_run": True,
                })
                return True
        if ".." in unquote(suffix).split("/"):
            json_response(
                self, {"success": False, "error": "invalid artifact name"}, 400,
            )
            return True
        path = _JOB_ANALYSIS_PATHS.get(suffix, f"/api/jobs/{job_id}{suffix}")
        forwarded: dict[str, object] = {}
        if method in {"POST", "PATCH"}:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except (TypeError, ValueError):
                length = 0
            if length <= 0 or length > 1024 * 1024:
                json_response(
                    self, {"success": False, "error": "invalid request body"}, 400,
                )
                return True
            body = self.rfile.read(length)
            if suffix in _JOB_ANALYSIS_PATHS:
                try:
                    payload = json.loads(body)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    json_response(
                        self, {"success": False, "error": "invalid request body"}, 400,
                    )
                    return True
                if not isinstance(payload, dict):
                    json_response(
                        self, {"success": False, "error": "invalid request body"}, 400,
                    )
                    return True
                payload["job_id"] = unquote(match.group(1))
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            forwarded = {
                "body": body,
                "content_type": str(
                    self.headers.get("Content-Type") or "application/json"
                ),
            }
        try:
            if (
                suffix in {
                    "/result", "/artifacts", "/supplementals",
                    "/custom-analyses",
                }
                or suffix.startswith("/artifacts/")
                or suffix.startswith("/supplementals/")
                or suffix.startswith("/custom-analyses/")
            ):
                routes = self._job_routes(
                    parsed, principal, for_artifact_storage=True,
                )
            else:
                routes = self._job_routes(parsed, principal)
            if method == "DELETE" and (
                suffix == "/artifacts" or suffix.startswith("/artifacts/")
            ):
                selected = str(parse_qs(parsed.query).get("server_id", [""])[0]).strip()
                if not routes and not selected:
                    routes = [self.state._local_route(port=0, online=True)]
                routes = list({
                    route.server_id: replace(route, port=0)
                    for route in routes
                }.values())
        except TargetUnavailable as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return True
        except (TargetNotFound, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 502)
            return True
        if method == "GET" and suffix == "/artifacts":
            selected = self._job_artifact_manifest(
                routes, job_id=unquote(match.group(1)), principal=principal,
            )
            if selected is None:
                json_response(
                    self, {"success": False, "error": "artifact was not found"}, 404,
                )
                return True
            route, artifacts, lookup_principal = selected
            if lookup_principal == "__public_jobs__":
                artifacts = [
                    item for item in artifacts
                    if str(item.get("artifact_role") or "output") != "input"
                ]
            json_response(self, {
                "success": True,
                "artifacts": artifacts,
                "storage_server_id": route.server_id,
            })
            return True
        last_response: tuple[ServiceRoute, GatewayResponse] | None = None
        principals = (
            read_principals(
                self.state,
                principal,
                unquote(match.group(1)),
                routes=routes,
            )
            if method == "GET" else (principal,)
        )
        for route in routes:
            for lookup_principal in principals:
                try:
                    response = self.state.route_request(
                        route,
                        path=path,
                        principal=lookup_principal,
                        method=method,
                        **forwarded,
                    )
                except (ConnectionError, ValueError):
                    continue
                last_response = (route, response)
                if response.status == 404:
                    continue
                if method == "GET" and suffix == "":
                    self._index_job_detail_response(
                        response, route=route, principal=principal,
                    )
                self._send_gateway_response(
                    response,
                    route=route,
                    include_route_identity=suffix in {"", "/result", "/artifacts"},
                )
                return True
        if last_response is not None:
            self._send_gateway_response(
                last_response[1],
                route=last_response[0],
            )
            return True
        json_response(
            self, {"success": False, "error": "job was not found"}, 404,
        )
        return True

    def _proxy_job_collection_request(self, parsed, *, method: str) -> bool:
        """Proxy retention control that is scoped to the caller, not one job.

        ``DELETE /api/jobs/artifacts`` clears every retained result the caller
        owns and ``DELETE /api/jobs`` clears their terminal history; both carry
        no job id.  The per-job pattern below cannot match them, so without
        this branch the request falls through to the Manager shell and the
        caller receives an HTML page instead of JSON.
        """
        storage_read = parsed.path == "/api/jobs/storage" and method == "GET"
        storage_delete = parsed.path == "/api/jobs/artifacts" and method == "DELETE"
        if parsed.path not in _JOB_COLLECTION_DELETE_PATHS and not storage_read:
            return False
        # These collection paths must never be parsed as a job whose id is
        # "artifacts"; they only support the retention delete.
        if method != "DELETE" and not storage_read:
            json_response(
                self,
                {"success": False, "error": "method not allowed"},
                405,
            )
            return True
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return True
        principal = str(session["username"])
        try:
            routes = self._job_routes(
                parsed, principal, for_artifact_storage=True,
            )
            if storage_read or storage_delete:
                selected = str(parse_qs(parsed.query).get("server_id", [""])[0]).strip()
                if not selected:
                    routes = [
                        route for route in routes
                        if route.server_id == self.state.server_id
                    ]
                if not routes and not selected:
                    routes = [self.state._local_route(port=0, online=True)]
                routes = list({
                    route.server_id: replace(route, port=0)
                    for route in routes
                }.values())
        except TargetUnavailable as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return True
        except (TargetNotFound, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 502)
            return True
        path = parsed.path
        if parsed.query:
            path = f"{path}?{parsed.query}"
        last_response: tuple[ServiceRoute, GatewayResponse] | None = None
        for route in routes:
            try:
                response = self.state.route_request(
                    route, path=path, principal=principal, method=method,
                )
            except (ConnectionError, ValueError):
                continue
            last_response = (route, response)
            if response.status == 404:
                continue
            self._send_gateway_response(response, route=route)
            return True
        if last_response is not None:
            self._send_gateway_response(last_response[1], route=last_response[0])
            return True
        json_response(
            self,
            {"success": False, "error": "retention storage is unavailable"},
            503,
        )
        return True

    def _proxy_job_stream(self, parsed) -> bool:
        match = re.fullmatch(
            r"/api/jobs/([A-Za-z0-9._-]{1,128})/stream", parsed.path,
        )
        if match is None:
            return False
        session = self._session()
        visitor = self._visitor_mode()
        public = session is None
        if visitor is not None:
            principal = visitor.principal
        elif public:
            principal = "__public_jobs__"
        else:
            principal = str(session["username"])
        path = self._forwarded_service_path(parsed)
        last_error: HTTPError | None = None
        connection_failed = False
        try:
            routes = self._job_routes(parsed, principal)
        except TargetUnavailable as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return True
        except (TargetNotFound, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 502)
            return True
        for route in routes:
            try:
                if route.remote:
                    upstream = self.state.federation_gateway.open_stream(
                        route,
                        path=path,
                        principal=principal,
                        last_event_id=str(self.headers.get("Last-Event-ID") or ""),
                    )
                else:
                    request = Request(
                        f"http://127.0.0.1:{route.port}{path}",
                        headers={
                            "Accept": "text/event-stream",
                            "X-FactorTester-Principal": principal,
                            "X-FactorTester-Manager": self.state.capability_token(),
                            "Last-Event-ID": str(self.headers.get("Last-Event-ID") or ""),
                        },
                    )
                    upstream = urlopen(request, timeout=15)
            except HTTPError as exc:
                last_error = exc
                if exc.code == 404:
                    continue
                body = exc.read()
                self.send_response(exc.code)
                self.send_header("Content-Type", exc.headers.get_content_type())
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return True
            except (ConnectionError, OSError, URLError):
                connection_failed = True
                continue
            with upstream:
                self.send_response(upstream.status)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("X-FactorTester-Service-Port", str(route.port))
                self.send_header("X-FactorTester-Service-Server", route.server_id)
                if route.branch:
                    self.send_header("X-FactorTester-Service-Branch", route.branch)
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    while chunk := read_available(upstream):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    pass
                return True
        if last_error is not None:
            body = last_error.read()
            self.send_response(last_error.code)
            self.send_header("Content-Type", last_error.headers.get_content_type())
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        if connection_failed:
            json_response(
                self,
                {"success": False, "error": "job stream service is unavailable"},
                503,
            )
            return True
        json_response(
            self, {"success": False, "error": "job stream was not found"}, 404,
        )
        return True
