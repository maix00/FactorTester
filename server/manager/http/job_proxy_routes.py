"""Execution writes, job reads, artifacts, and stream forwarding."""

from __future__ import annotations

import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.request import Request, urlopen

from server.manager.domain.federation import (
    ServiceRoute,
    TargetNotFound,
    TargetUnavailable,
)
from server.manager.http.gateway import GatewayResponse
from server.manager.http.responses import json_response


_SERVICE_WRITE_PATTERNS = {
    "POST": (
        r"/api/agent-flow/agents/[A-Za-z0-9._-]{1,256}/resume",
        r"/api/product-groups",
        r"/api/runs/capability-preview",
        r"/api/runs(?:/preview)?",
        r"/api/runs/[^/]{1,128}/clone-workspace",
        r"/api/jobs/[A-Za-z0-9._-]{1,128}/(?:approve|cancel|continue|retry)",
    ),
    "PUT": (),
    "DELETE": (),
    "PATCH": (r"/api/profile-research/[^/]{1,512}/lifecycle",),
}
_JOB_ANALYSIS_PATHS = {
    "/group-detail": "/get_group_detail",
    "/group-ranking-detail": "/get_group_ranking_detail",
    "/group-snapshot": "/get_group_snapshot",
    "/group-order-flow": "/get_group_order_flow",
}


class JobProxyRoutesMixin:
    """Forward execution requests after selection and preserve provenance."""
    def _proxy_service_write(self, parsed, *, method: str) -> bool:
        patterns = _SERVICE_WRITE_PATTERNS.get(method, ())
        if not any(re.fullmatch(pattern, parsed.path) for pattern in patterns):
            return False
        session = self._session()
        if session is None:
            json_response(
                self, {"success": False, "error": "login required"}, 401,
            )
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
            body = self._normalise_run_submission_identity(
                body, principal=str(session["username"]),
            )
            if body is None:
                return True
            body = self._prepare_manager_run_context(
                body, principal=str(session["username"]),
            )
            if body is None:
                return True
        if method == "POST" and parsed.path == "/api/runs":
            route = self._capable_service_route(
                parsed,
                body=body,
                principal=str(session["username"]),
                content_type=content_type,
            )
        else:
            route = self._service_route(parsed)
        if route is None:
            return True
        try:
            response = self.state.route_request(
                route,
                path=self._forwarded_service_path(parsed),
                principal=str(session["username"]),
                method=method,
                body=body,
                content_type=content_type,
                origin_server_id=(
                    self.state.server_id
                    if method == "POST" and parsed.path == "/api/runs"
                    else ""
                ),
            )
        except (ConnectionError, ValueError):
            json_response(
                self, {"success": False, "error": "service port is unavailable"}, 502,
            )
            return True
        if method == "POST" and parsed.path == "/api/runs":
            self.state.record_run_submission(
                response,
                principal=str(session["username"]),
                route=route,
                origin_server_id=self.state.server_id,
            )
        self._send_gateway_response(response, route=route)
        return True
    def _send_gateway_response(
        self,
        response: GatewayResponse,
        *,
        port: int | None = None,
        route: ServiceRoute | None = None,
    ) -> None:
        selected_port = int(route.port if route is not None else (port or 0))
        body = response.body
        content_type = response.content_type
        if content_type == "application/json":
            try:
                value = response.json_object()
                value.setdefault("port", selected_port)
                body = json.dumps(value, ensure_ascii=False).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
                pass
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
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _job_routes(self, parsed, principal: str | None = None) -> list[ServiceRoute]:
        """Resolve job origins, using peer Managers when federation is active."""
        query = parse_qs(parsed.query, keep_blank_values=True)
        raw_port = str(query.get("port", [""])[0] or "").strip()
        if raw_port and not raw_port.isdigit():
            raise ValueError("port must be an integer")
        port = int(raw_port) if raw_port else None
        server_id = str(query.get("server_id", [""])[0] or "").strip()
        branch = str(query.get("branch", [""])[0] or "").strip()
        feature = str(query.get("feature", [""])[0] or "").strip()
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
            offline_remote = [
                route for route in routes if route.remote and not route.online
            ]
            if offline_remote:
                names = ", ".join(
                    f"{route.server_id}:{route.port}" for route in offline_remote
                )
                raise TargetUnavailable(f"registered target is offline: {names}")
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

    def _proxy_job_request(self, parsed, *, method: str) -> bool:
        match = re.fullmatch(
            r"/api/jobs/([A-Za-z0-9._-]{1,128})"
            r"(/result|/artifacts(?:/generate)?"
            r"|/group-detail|/group-ranking-detail|/group-snapshot"
            r"|/group-order-flow)?",
            parsed.path,
        )
        if match is None:
            return False
        suffix = match.group(2) or ""
        if method == "POST" and (
            suffix != "/artifacts/generate"
            and suffix not in _JOB_ANALYSIS_PATHS
        ):
            return False
        session = self._session()
        suffix_value = suffix
        public = (
            session is None
            and method == "GET"
            and suffix_value in {"", "/result", "/artifacts"}
        )
        if session is None and not public:
            json_response(
                self, {"success": False, "error": "login required"}, 401,
            )
            return True
        if public:
            principal = "__public_jobs__"
        else:
            principal = str(session["username"])
        job_id = quote(unquote(match.group(1)), safe="")
        if ".." in unquote(suffix).split("/"):
            json_response(
                self, {"success": False, "error": "invalid artifact name"}, 400,
            )
            return True
        path = _JOB_ANALYSIS_PATHS.get(suffix, f"/api/jobs/{job_id}{suffix}")
        forwarded: dict[str, object] = {}
        if method == "POST":
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
            routes = self._job_routes(parsed, principal)
        except TargetUnavailable as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return True
        except (TargetNotFound, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 502)
            return True
        last_response: tuple[ServiceRoute, GatewayResponse] | None = None
        for route in routes:
            try:
                response = self.state.route_request(
                    route,
                    path=path,
                    principal=principal,
                    method=method,
                    **forwarded,
                )
            except (ConnectionError, ValueError):
                continue
            last_response = (route, response)
            if response.status == 404:
                continue
            self._send_gateway_response(response, route=route)
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

    def _proxy_job_stream(self, parsed) -> bool:
        match = re.fullmatch(
            r"/api/jobs/([A-Za-z0-9._-]{1,128})/stream", parsed.path,
        )
        if match is None:
            return False
        session = self._session()
        public = session is None
        principal = "__public_jobs__" if public else str(session["username"])
        path = self._forwarded_service_path(parsed)
        job_id = unquote(match.group(1))
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
                    event_buffer = b""
                    while chunk := upstream.read(4096):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        event_buffer = (event_buffer + chunk).replace(b"\r\n", b"\n")
                        while b"\n\n" in event_buffer:
                            frame, event_buffer = event_buffer.split(b"\n\n", 1)
                            data = b"\n".join(
                                line[5:].strip()
                                for line in frame.splitlines()
                                if line.startswith(b"data:")
                            )
                            if not data:
                                continue
                            try:
                                event = json.loads(data.decode("utf-8"))
                            except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
                                continue
                            if isinstance(event, dict):
                                self.state.job_index.upsert(principal, [{
                                    **event,
                                    "job_id": str(event.get("job_id") or job_id),
                                    "port": route.port,
                                    "service_port": route.port,
                                    "server_id": route.server_id,
                                    "server_endpoint": route.endpoint,
                                    "server_host": urlparse(route.endpoint).hostname or "",
                                    "server_role": route.role,
                                    "server_branch": route.branch,
                                    "server_revision": route.revision,
                                    "updated_at": str(event.get("updated_at") or time.time()),
                                }], emit_events=not route.remote)
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
