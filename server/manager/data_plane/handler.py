"""Thin HTTP dispatch shells for isolated client and peer data listeners."""

from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler
from urllib.error import URLError
from urllib.parse import urlparse

from server.manager.data_plane.destination import (
    receive_destination,
    receive_local_upload,
)
from server.manager.data_plane.direct import serve_direct_pull
from server.manager.data_plane.direct_push import serve_direct_push
from server.manager.data_plane.integrity import IntegrityError
from server.manager.data_plane.origin import serve_local_download, serve_origin
from server.manager.data_plane.responses import json_error
from server.manager.data_plane.routes import (
    DataPlaneSurface,
    match_transfer_route,
    method_allowed,
)
from server.manager.transfers.models import TransferMode
from server.manager.transfers.peer_gateway import PeerControlError
from server.manager.transfers.planner import NodeUnavailable


class _DataPlaneHandler(BaseHTTPRequestHandler):
    surface: DataPlaneSurface
    server: object

    def _dispatch(self) -> None:
        if urlparse(self.path).path == "/healthz":
            self._health()
            return
        route = match_transfer_route(self.path, surface=self.surface)
        if route is None:
            json_error(self, 404, "transfer data route not found")
            return
        if not method_allowed(route.action, self.command):
            json_error(self, 405, "method is not allowed for transfer route")
            return
        telemetry_handle = None
        try:
            runtime = self.server.runtime
            context = runtime.context(route.attempt_id)
            # HEAD probes metadata for the same attempt. A zero-byte completion
            # must not overwrite the GET's persisted transfer statistics.
            if self.command != "HEAD":
                telemetry_handle = runtime.begin_transfer_telemetry(
                    context,
                    surface=self.surface.value,
                    action=route.action,
                )
            self._ft_transfer_telemetry = telemetry_handle
            self._handler(route.action, context)(
                self, runtime, context,
            )
        except PermissionError as exc:
            json_error(self, 403, str(exc))
        except KeyError as exc:
            json_error(self, 404, str(exc))
        except FileNotFoundError as exc:
            json_error(self, 410, str(exc))
        except (IntegrityError, ValueError) as exc:
            json_error(self, 422, str(exc))
        except (NodeUnavailable, URLError, TimeoutError, ConnectionError) as exc:
            json_error(self, 503, str(exc), code="node_unreachable")
        except PeerControlError as exc:
            json_error(self, 503, str(exc), code=exc.code)
        except (BrokenPipeError, ConnectionResetError):
            return
        except RuntimeError as exc:
            json_error(self, 500, str(exc))
        finally:
            if telemetry_handle is not None:
                self.server.runtime.finish_transfer_telemetry(telemetry_handle)
                self._ft_transfer_telemetry = None

    def _handler(self, action: str, context):
        if action == "origin":
            return serve_origin
        if action == "destination":
            return receive_destination
        if action == "download":
            return (
                serve_local_download
                if context.attempt.mode is TransferMode.LOCAL
                else serve_direct_pull
            )
        return (
            receive_local_upload
            if context.attempt.mode is TransferMode.LOCAL
            else serve_direct_push
        )

    def _health(self) -> None:
        body = (
            '{"success":true,"surface":"'
            + self.surface.value
            + '","server_id":"'
            + self.server.runtime.server_id
            + '"}'
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch()

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch()

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch()

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(f"[data-plane:{self.surface.value}] " + (fmt % args) + "\n")


class ClientDataPlaneHandler(_DataPlaneHandler):
    surface = DataPlaneSurface.CLIENT

    def end_headers(self) -> None:
        origin = str(self.headers.get("Origin") or "").strip().rstrip("/")
        if origin and origin in self.server.runtime.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header(
                "Access-Control-Expose-Headers",
                "Accept-Ranges, Content-Length, Content-Range, ETag",
            )
        super().end_headers()

    def do_OPTIONS(self) -> None:  # noqa: N802
        origin = str(self.headers.get("Origin") or "").strip().rstrip("/")
        if not origin or origin not in self.server.runtime.allowed_origins:
            json_error(self, 403, "client origin is not allowed")
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, PUT, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Authorization, Content-Type, Range",
        )
        if str(
            self.headers.get("Access-Control-Request-Private-Network") or ""
        ).strip().lower() == "true":
            # Chromium/WebKit may send this preflight when a page opened from
            # loopback reaches the host's private LAN 7997 address.  The
            # origin has already passed the explicit allow-list check above;
            # acknowledge only that requested private-network transition.
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()


class PeerDataPlaneHandler(_DataPlaneHandler):
    surface = DataPlaneSurface.PEER
