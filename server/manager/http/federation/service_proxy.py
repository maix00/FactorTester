"""Semantic slice of the authenticated federation HTTP adapter."""

from __future__ import annotations

import base64
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from server.manager.domain.federation import TargetNotFound, TargetUnavailable
from server.manager.http.responses import json_response
from server.manager.http.streaming import read_available


class FederationServiceProxyRoutesMixin:
    @staticmethod
    def _federation_path_allowed(path: str) -> bool:
        return (
            path in {
                "/get_group_detail",
                "/get_group_ranking_detail",
                "/get_group_snapshot",
                "/get_group_order_flow",
            }
            or
            path == "/api/jobs"
            or path.startswith("/api/jobs/")
            or path == "/api/runs"
            or re.fullmatch(
                r"/api/agent-flow/agents/[A-Za-z0-9._-]{1,256}/resume",
                path,
            )
            or path == "/api/research-agent-executions"
            or (
                path.startswith("/api/research-graphs/")
                and not path.startswith("/api/research-graphs/user-library")
            )
            or path.startswith("/api/trial-plans/")
            or path.startswith("/api/product-groups")
            or path == "/custom-factors/api/internal/public-source-applied"
        )
    def _federation_proxy(self) -> None:
        if not self._has_federation_proxy_token():
            json_response(
                self,
                {"success": False, "error": "federation proxy is unauthorized"},
                401,
            )
            return
        try:
            payload = self._json_body(16 * 1024 * 1024)
            server_id = str(payload.get("server_id") or "").strip()
            port = int(payload.get("port") or 0)
            path = str(payload.get("path") or "").strip()
            principal = str(payload.get("principal") or "").strip()
            method = str(payload.get("method") or "GET").upper()
            content_type = str(payload.get("content_type") or "application/json")
            origin_server_id = str(payload.get("origin_server_id") or "").strip()
            if server_id != self.state.server_id:
                raise ValueError("federation target server_id does not match")
            if not 1 <= port <= 65535:
                raise ValueError("federation target port is invalid")
            if not principal:
                raise ValueError("federation principal is required")
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                raise ValueError("federation method is not supported")
            if not self._federation_path_allowed(path):
                raise ValueError("federation path is not allowed")
            encoded = str(payload.get("body_b64") or "")
            body = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        try:
            route = self.state.route_for(
                server_id=self.state.server_id,
                port=port,
            )
            response = self.state.route_request(
                route,
                path=path,
                principal=principal,
                method=method,
                body=body or None,
                content_type=content_type,
            )
        except TargetUnavailable as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return
        except (TargetNotFound, ConnectionError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 502)
            return
        if method == "POST" and path == "/api/runs" and origin_server_id:
            self.state.record_run_submission(
                response,
                principal=principal,
                route=route,
                origin_server_id=origin_server_id,
            )
        envelope = {
            "success": True,
            "status": response.status,
            "content_type": response.content_type,
            "content_disposition": response.content_disposition,
            "etag": response.etag,
            "body_b64": base64.b64encode(response.body).decode("ascii"),
        }
        json_response(self, envelope, response.status)

    def _federation_stream(self) -> None:
        """Proxy one job SSE stream to a service owned by this Manager.

        The peer Manager is the only cross-host hop.  This endpoint never
        resolves another remote route, which prevents a registration cycle
        from turning into an unbounded proxy chain.
        """
        if not self._has_federation_proxy_token():
            json_response(
                self,
                {"success": False, "error": "federation proxy is unauthorized"},
                401,
            )
            return
        try:
            payload = self._json_body(256 * 1024)
            server_id = str(payload.get("server_id") or "").strip()
            port = int(payload.get("port") or 0)
            path = str(payload.get("path") or "").strip()
            principal = str(payload.get("principal") or "").strip()
            last_event_id = str(payload.get("last_event_id") or "").strip()[:512]
            parsed_path = urlparse(path)
            if server_id != self.state.server_id:
                raise ValueError("federation target server_id does not match")
            if not 1 <= port <= 65535:
                raise ValueError("federation target port is invalid")
            if not principal:
                raise ValueError("federation principal is required")
            if parsed_path.scheme or parsed_path.netloc:
                raise ValueError("federation stream path must be relative")
            if not re.fullmatch(
                r"/api/jobs/[A-Za-z0-9._-]{1,128}/stream",
                parsed_path.path,
            ):
                raise ValueError("federation stream path is not allowed")
            if not self._federation_path_allowed(parsed_path.path):
                raise ValueError("federation path is not allowed")
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return

        try:
            route = self.state.route_for(
                server_id=self.state.server_id,
                port=port,
            )
            if route.remote:
                raise ValueError("federation stream cannot be chained")
        except TargetUnavailable as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return
        except (TargetNotFound, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 502)
            return

        forwarded_path = parsed_path.path
        if parsed_path.query:
            forwarded_path += f"?{parsed_path.query}"
        request = Request(
            f"http://127.0.0.1:{route.port}{forwarded_path}",
            headers={
                "Accept": "text/event-stream",
                "X-FactorTester-Principal": principal,
                "X-FactorTester-Manager": self.state.capability_token(),
                "Last-Event-ID": last_event_id,
            },
        )
        try:
            upstream = urlopen(request, timeout=15)
        except HTTPError as exc:
            body = exc.read(4 * 1024 * 1024)
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get_content_type())
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        except (URLError, OSError):
            json_response(
                self,
                {"success": False, "error": "local service stream is unavailable"},
                503,
            )
            return

        with upstream:
            self.send_response(getattr(upstream, "status", 200))
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("X-FactorTester-Service-Port", str(route.port))
            self.send_header("X-FactorTester-Service-Server", route.server_id)
            if route.branch:
                self.send_header("X-FactorTester-Service-Branch", route.branch)
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                while chunk := read_available(upstream):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
