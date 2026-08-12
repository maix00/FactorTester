"""Serve the read-only SQLite browser from the Manager process.

The Manager owns the shared database view.  Business services are task
workers, so a database request must not be routed through a preferred worker
port or depend on that worker's session state.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from server.manager.http.sqlite_ui import decorate_sqlite_html


@dataclass(frozen=True)
class ManagerSQLiteResponse:
    status: int
    body: bytes
    content_type: str = "text/html; charset=utf-8"
    headers: tuple[tuple[str, str], ...] = ()


class ManagerSQLiteWeb:
    """Lazy WSGI adapter for the Manager-owned sqlite-web application."""

    def __init__(self, state) -> None:
        self._state = state
        self._app = None

    def _application(self):
        if self._app is None:
            # sqlite-web's existing gateway hook validates these headers
            # against the process environment.  The Manager is the gateway
            # here, so establish the same capability in its own process.
            os.environ["GTHT_MANAGER_CAPABILITY_TOKEN"] = (
                self._state.capability_token()
            )
            from server.services.sqlite_web_mount import build_sqlite_web_app

            self._app = build_sqlite_web_app(self._state.capability_token())
        return self._app

    def request(
        self,
        *,
        method: str,
        path: str,
        query: str,
        principal: str,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
    ) -> ManagerSQLiteResponse:
        """Run one Manager-authenticated request through the local WSGI app."""
        prefix = "/sqlite-web"
        parsed = urlparse(path)
        path_info = parsed.path.removeprefix(prefix) or "/"
        if not path_info.startswith("/"):
            path_info = "/" + path_info
        request_headers = {
            str(key).lower(): str(value)
            for key, value in (headers or {}).items()
        }
        environ = {
            "REQUEST_METHOD": method.upper(),
            "SCRIPT_NAME": prefix,
            "PATH_INFO": path_info,
            "QUERY_STRING": query,
            "SERVER_NAME": "127.0.0.1",
            "SERVER_PORT": "7998",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "REMOTE_ADDR": "127.0.0.1",
            "wsgi.errors": io.StringIO(),
            "wsgi.input": io.BytesIO(body),
            "wsgi.multiprocess": False,
            "wsgi.multithread": True,
            "wsgi.run_once": False,
            "wsgi.url_scheme": "http",
            "wsgi.version": (1, 0),
            "wsgi.file_wrapper": _FileWrapper,
            "CONTENT_LENGTH": str(len(body)),
            "HTTP_X_FACTORTESTER_PRINCIPAL": principal,
            "HTTP_X_FACTORTESTER_MANAGER": self._state.capability_token(),
        }
        for key, value in request_headers.items():
            if key == "content-type":
                environ["CONTENT_TYPE"] = value
            elif key == "content-length":
                environ["CONTENT_LENGTH"] = value
            elif key != "host":
                environ["HTTP_" + key.upper().replace("-", "_")] = value

        result_status = 500
        result_headers: list[tuple[str, str]] = []

        def start_response(status: str, response_headers, exc_info=None):
            nonlocal result_status, result_headers
            result_status = int(str(status).split(" ", 1)[0])
            result_headers = [
                (str(key), str(value)) for key, value in response_headers
            ]
            if exc_info is not None:
                return lambda data: None
            return None

        response_iter = self._application().wsgi_app(environ, start_response)
        try:
            response_body = b"".join(response_iter)
        finally:
            close = getattr(response_iter, "close", None)
            if close is not None:
                close()
        content_type = next(
            (
                value
                for key, value in result_headers
                if key.lower() == "content-type"
            ),
            "text/html; charset=utf-8",
        )
        response_body = decorate_sqlite_html(response_body, content_type)
        return ManagerSQLiteResponse(
            status=result_status,
            body=response_body,
            content_type=content_type,
            headers=tuple(result_headers),
        )


class _FileWrapper:
    """Minimal WSGI file wrapper advertised to Flask/Werkzeug."""

    def __init__(self, filelike, *args, **kwargs) -> None:
        self.filelike = filelike

    def __iter__(self):
        while True:
            chunk = self.filelike.read(64 * 1024)
            if not chunk:
                return
            yield chunk
