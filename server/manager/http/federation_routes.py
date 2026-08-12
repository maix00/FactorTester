"""Authenticated peer registration, synchronization, and proxy routes."""

from __future__ import annotations

import base64
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from server.jobs.artifact_data_plane import (
    artifact_data_endpoint,
    artifact_data_port,
    artifact_data_url,
)
from server.manager.domain.federation import TargetNotFound, TargetUnavailable
from server.manager.http.responses import json_response


class FederationRoutesMixin:
    """Expose the narrow machine-to-machine Manager federation protocol."""

    @staticmethod
    def _federation_path_allowed(path: str) -> bool:
        return (
            path == "/api/jobs"
            or path.startswith("/api/jobs/")
            or path == "/api/runs"
            or path.startswith("/api/runs/")
            or path.startswith("/api/agent-flow/")
            or path.startswith("/api/research-graphs/")
            or path.startswith("/api/research-evidence/")
            or path.startswith("/api/trial-plans/")
            or path.startswith("/api/run-specs/")
            or path.startswith("/api/profile-research/")
            or path.startswith("/api/product-groups")
        )

    def _federation_register(self) -> None:
        if not self._has_federation_registration_token():
            json_response(
                self,
                {"success": False, "error": "federation registration is unauthorized"},
                401,
            )
            return
        try:
            value = self.state.federation_registry.register(
                self._json_body(512 * 1024),
            )
        except (TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        public = {
            key: item
            for key, item in value.items()
            if key not in {"proxy_token"}
        }
        forwarded_proto = str(
            self.headers.get("X-Forwarded-Proto") or "http"
        ).split(",", 1)[0].strip().lower()
        if forwarded_proto not in {"http", "https"}:
            forwarded_proto = "http"
        advertised_endpoint = os.environ.get(
            "FACTORTESTER_MANAGER_PUBLIC_ENDPOINT", ""
        ).strip().rstrip("/")
        if not advertised_endpoint:
            host = str(self.headers.get("Host") or "").strip()
            if host:
                advertised_endpoint = f"{forwarded_proto}://{host}"
        peer = None
        if advertised_endpoint:
            try:
                federation_config = self.state.federation_config()
                artifact_endpoint = str(
                    os.environ.get("FACTORTESTER_ARTIFACT_PUBLIC_ENDPOINT")
                    or federation_config.get("artifact_endpoint")
                    or ""
                ).strip().rstrip("/")
                peer = self.state.peer_registration_payload(
                    advertised_endpoint,
                    artifact_endpoint=artifact_endpoint,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                sys.stderr.write(f"[federation] peer descriptor unavailable: {exc}\n")
        # Registration is service discovery only; task summaries are on-demand.
        json_response(self, {
            "success": True,
            "server": public,
            # This is returned only over the already authenticated
            # registration channel.  It lets the caller route back to this
            # Manager's fixed service (normally remote 8000) without exposing
            # any service port directly.
            "peer": peer,
        })

    def _federation_sync_events(self) -> None:
        """Serve the local Manager event stream to an authenticated peer."""
        if not self._has_federation_proxy_token():
            json_response(
                self,
                {"success": False, "error": "federation proxy is unauthorized"},
                401,
            )
            return
        try:
            payload = self._json_body(2 * 1024 * 1024)
            requester = str(payload.get("requester_server_id") or "").strip()
            after_sequence = int(payload.get("after_sequence") or 0)
            limit = int(payload.get("limit") or 100)
            if not requester:
                raise ValueError("requester_server_id is required")
            if requester == self.state.server_id:
                raise ValueError("requester_server_id must identify a peer")
            if after_sequence < 0:
                raise ValueError("after_sequence must not be negative")
            if not 1 <= limit <= 200:
                raise ValueError("limit must be between 1 and 200")
            value = self.state.job_index.events_for_peer(
                requester,
                after_sequence=after_sequence,
                limit=limit,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, value)

    def _federation_jobs_query(self) -> None:
        """Serve a bounded local task projection to a peer Manager.

        The proxy token authenticates the peer-to-peer request.  The local
        aggregation methods are explicitly called with federation disabled so
        this endpoint cannot recurse through the other Manager.
        """
        if not self._has_federation_proxy_token():
            json_response(
                self,
                {"success": False, "error": "federation proxy is unauthorized"},
                401,
            )
            return
        try:
            payload = self._json_body(64 * 1024)
            requester = str(payload.get("requester_server_id") or "").strip()
            principal = str(payload.get("principal") or "").strip()
            scope = str(payload.get("scope") or "").strip().lower()
            page = int(payload.get("page") or 1)
            limit = int(payload.get("limit") or 100)
            if not requester:
                raise ValueError("requester_server_id is required")
            if requester == self.state.server_id:
                raise ValueError("requester_server_id must identify a peer")
            if not principal:
                raise ValueError("principal is required")
            if scope not in {"mine", "server"}:
                raise ValueError("scope must be mine or server")
            if page < 1 or not 1 <= limit <= 100:
                raise ValueError("page or limit is invalid")
            if scope == "server":
                value = self.state.aggregate_server_jobs(
                    principal=principal,
                    cursor="",
                    limit=limit,
                    _allow_federation=False,
                )
            else:
                value = self.state.aggregate_account_jobs(
                    principal=principal,
                    scope="mine",
                    page=page,
                    limit=limit,
                    _allow_federation=False,
                )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {
            **value,
            "success": True,
            "source_server_id": self.state.server_id,
            "source_scope": scope,
        })

    def _federation_sync_reconcile(self) -> None:
        """Return a bounded current projection for a peer's repair request."""
        if not self._has_federation_proxy_token():
            json_response(
                self,
                {"success": False, "error": "federation proxy is unauthorized"},
                401,
            )
            return
        try:
            payload = self._json_body(2 * 1024 * 1024)
            requester = str(payload.get("requester_server_id") or "").strip()
            raw_job_ids = payload.get("job_ids") or []
            limit = int(payload.get("limit") or 200)
            if not requester:
                raise ValueError("requester_server_id is required")
            if requester == self.state.server_id:
                raise ValueError("requester_server_id must identify a peer")
            if not isinstance(raw_job_ids, list):
                raise ValueError("job_ids must be a list")
            if not 1 <= limit <= 200:
                raise ValueError("limit must be between 1 and 200")
            jobs = self.state.job_index.reconcile_for_peer(
                requester,
                job_ids=raw_job_ids[:200],
                limit=limit,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {
            "success": True,
            "source_server_id": self.state.server_id,
            "jobs": jobs,
        })

    def _federation_sync(self) -> None:
        """Run one manual event pull from the Manager settings page."""
        if not self._require_super_admin_session():
            return
        json_response(self, {
            "success": True,
            "reports": self.state.sync_federation_once(),
        })

    def _federation_artifact_ticket(self) -> None:
        """Mint a ticket for this Manager's host-local 7997 data plane."""
        if not self._has_federation_proxy_token():
            json_response(
                self,
                {"success": False, "error": "federation proxy is unauthorized"},
                401,
            )
            return
        try:
            payload = self._json_body(64 * 1024)
            server_id = str(payload.get("server_id") or "").strip()
            job_id = str(payload.get("job_id") or "").strip()
            name = str(payload.get("name") or "").strip()
            principal = str(payload.get("principal") or "").strip()
            preview = bool(payload.get("preview"))
            archive = bool(payload.get("archive"))
            if server_id != self.state.server_id:
                raise ValueError("federation target server_id does not match")
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", job_id):
                raise ValueError("job_id is invalid")
            if archive:
                name = "__archive__"
            elif not name or "/" in name or "\\" in name or ".." in name:
                raise ValueError("artifact name is invalid")
            if not principal:
                raise ValueError("federation principal is required")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        from server.jobs.repository import JobRepository

        repository = JobRepository()
        job = repository.load(job_id)
        if job is None:
            json_response(self, {"success": False, "error": "job was not found"}, 404)
            return
        if principal != "__public_jobs__" and job.owner != principal:
            json_response(self, {"success": False, "error": "job was not found"}, 404)
            return
        if not archive:
            metadata = repository.load_artifact(
                job_id=job_id,
                name=name,
                owner=job.owner,
            )
            if metadata is None or str(metadata.get("state") or "") != "active":
                json_response(self, {"success": False, "error": "artifact was not found"}, 404)
                return
            if (
                principal == "__public_jobs__"
                and str(metadata.get("artifact_role") or "output") == "input"
            ):
                json_response(self, {"success": False, "error": "登录后才能查看运行输入"}, 401)
                return
        endpoint = str(
            os.environ.get("FACTORTESTER_MANAGER_PUBLIC_ENDPOINT") or ""
        ).strip().rstrip("/")
        if not endpoint:
            host = str(self.headers.get("Host") or "").strip()
            if host:
                endpoint = f"http://{host}"
        try:
            data_endpoint = artifact_data_endpoint(
                endpoint=endpoint or "http://127.0.0.1:7998",
                port=artifact_data_port(),
            )
            ticket = self.state.artifact_ticket_codec().issue(
                owner=job.owner,
                job_id=job_id,
                name=name,
                server_id=self.state.server_id,
                preview=preview,
            )
        except (OSError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return
        json_response(self, {
            "success": True,
            "ticket": ticket,
            "data_endpoint": data_endpoint,
            "url": artifact_data_url(
                data_endpoint,
                job_id=job_id,
                name=name,
                ticket=ticket,
            ),
        })

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
        except (URLError, OSError) as exc:
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
                while chunk := upstream.read(4096):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass

    def _federation_capabilities(self) -> None:
        """Return this Manager's data-source capability projection to a peer."""
        if not self._has_federation_proxy_token():
            json_response(
                self,
                {"success": False, "error": "federation capability is unauthorized"},
                401,
            )
            return
        try:
            payload = self._json_body(4 * 1024 * 1024)
            if not isinstance(payload, dict):
                raise ValueError("federation capability payload must be an object")
            value = self.state.local_capability_snapshot(payload)
            requested_port = payload.get("port")
            requested_branch = str(payload.get("branch") or "").strip()
            targets = self.state.local_service_routes(include_offline=False)
            if requested_port not in (None, ""):
                try:
                    requested_port = int(requested_port)
                except (TypeError, ValueError) as exc:
                    raise ValueError("capability port must be an integer") from exc
                targets = [
                    route for route in targets
                    if route.port == requested_port
                    and (not requested_branch or route.branch == requested_branch)
                ]
                if not targets:
                    raise ValueError(
                        "requested capability port is not online on this Manager"
                    )
            target = min(
                targets,
                key=self.state.route_selection_key,
                default=None,
            )
        except (TypeError, ValueError, OSError, RuntimeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {
            "success": True,
            "server_id": self.state.server_id,
            "server_role": self.state.server_role,
            "target": (
                {
                    "server_id": self.state.server_id,
                    "server_role": self.state.server_role,
                    **target.as_dict(),
                }
                if target is not None else {
                    "server_id": self.state.server_id,
                    "server_role": self.state.server_role,
                }
            ),
            "ports": [
                route.as_dict()
                for route in self.state.local_service_routes(
                    include_offline=False,
                )
            ],
            **value,
        })

    def _federation_servers(self) -> None:
        if not self._has_api_authorization():
            self._require_capability()
            return
        servers = []
        for item in self.state.federation_registry.servers(include_offline=True):
            servers.append({
                key: value
                for key, value in item.items()
                if key not in {"proxy_token"}
            })
        json_response(self, {
            "success": True,
            "server_id": self.state.server_id,
            "role": self.state.server_role,
            "local_targets": [
                route.as_dict()
                for route in self.state.local_service_routes(include_offline=False)
            ],
            "servers": servers,
        })

    def _has_super_admin_session(self) -> bool:
        session = self._session()
        return bool(
            self._has_secure_ui_transport()
            and session
            and str(session.get("role") or "") == "super_admin"
        )

    def _require_super_admin_session(self) -> bool:
        if self._has_super_admin_session():
            return True
        session = self._session()
        status = 401 if session is None else 403
        json_response(
            self,
            {
                "success": False,
                "error": "super administrator permission required",
            },
            status,
        )
        return False

    def _federation_config(self) -> None:
        if not self._require_super_admin_session():
            return
        json_response(self, {
            "success": True,
            "config": self.state.federation_config(public=True),
            "status": self.state.federation_config_status(),
            "available_ports": [
                route.as_dict()
                for route in self.state.local_service_routes(
                    include_offline=False,
                )
            ],
        })

    def _update_federation_config(self) -> None:
        if not self._require_super_admin_session():
            return
        try:
            value = self.state.update_federation_config(
                self._json_body(256 * 1024),
            )
        except (TypeError, ValueError, OSError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {"success": True, **value})
