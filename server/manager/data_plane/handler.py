"""Thin HTTP dispatch shell for native 7997 transfer routes."""

from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from server.manager.data_plane.destination import receive_destination
from server.manager.data_plane.integrity import IntegrityError
from server.manager.data_plane.origin import serve_origin
from server.manager.data_plane.relay import RelayConflict, RelayTimeout
from server.manager.data_plane.relay_routes import (
    receive_producer,
    serve_consumer,
)
from server.manager.data_plane.responses import empty_response, json_error
from server.manager.data_plane.routes import match_transfer_route, method_allowed


class DataPlaneHandler(BaseHTTPRequestHandler):
    server: object

    def _dispatch(self) -> None:
        if urlparse(self.path).path == "/healthz":
            self._health()
            return
        route = match_transfer_route(self.path)
        if route is None:
            json_error(self, 404, "transfer data route not found")
            return
        if not method_allowed(route.action, self.command):
            json_error(self, 405, "method is not allowed for transfer route")
            return
        try:
            context = self.server.runtime.context(route.attempt_id)
            {
                "origin": serve_origin,
                "producer": receive_producer,
                "consumer": serve_consumer,
                "destination": receive_destination,
            }[route.action](self, self.server.runtime, context)
        except PermissionError as exc:
            json_error(self, 403, str(exc))
        except KeyError as exc:
            json_error(self, 404, str(exc))
        except FileNotFoundError as exc:
            json_error(self, 410, str(exc))
        except (IntegrityError, ValueError) as exc:
            json_error(self, 422, str(exc))
        except RelayConflict as exc:
            json_error(self, 409, str(exc))
        except RelayTimeout as exc:
            json_error(self, 504, str(exc))
        except (BrokenPipeError, ConnectionResetError):
            return
        except RuntimeError as exc:
            json_error(self, 500, str(exc))

    def _health(self) -> None:
        if self.command not in {"GET", "HEAD"}:
            json_error(self, 405, "health route supports GET and HEAD")
            return
        body = (
            b'{"success":true,"service":"factor-data-plane",'
            + f'"server_id":"{self.server.runtime.server_id}"'.encode("utf-8")
            + b"}"
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
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

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Allow", "GET, HEAD, PUT, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Authorization, Content-Type, Range, X-FactorTester-Node-ID",
        )
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("[data-plane] " + (fmt % args) + "\n")
