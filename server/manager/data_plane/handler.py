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
        try:
            context = self.server.runtime.context(route.attempt_id)
            self._handler(route.action, context)(
                self, self.server.runtime, context,
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
        except (BrokenPipeError, ConnectionResetError):
            return
        except RuntimeError as exc:
            json_error(self, 500, str(exc))

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


class PeerDataPlaneHandler(_DataPlaneHandler):
    surface = DataPlaneSurface.PEER
