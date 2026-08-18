"""Bounded HTTP and WebSocket forwarding for the local Mihomo controller."""

from __future__ import annotations

import http.client
import select
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class MihomoProxyError(RuntimeError):
    """The local controller could not serve a dashboard request."""


_MAX_BODY = 8 * 1024 * 1024
_MAX_RESPONSE = 16 * 1024 * 1024
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}
_FORWARDED_REQUEST_HEADERS = {
    "accept", "content-type", "if-none-match", "if-modified-since",
    "user-agent", "sec-websocket-key", "sec-websocket-version",
    "sec-websocket-protocol", "sec-websocket-extensions", "origin",
}


def forward_http(handler, target: str, method: str, host: str, port: int) -> None:
    body = _request_body(handler)
    headers = {
        key: value
        for key, value in handler.headers.items()
        if key.lower() in _FORWARDED_REQUEST_HEADERS
    }
    headers["Host"] = f"{host}:{port}"
    headers["Connection"] = "close"
    connection = None
    try:
        connection = http.client.HTTPConnection(host, port, timeout=10)
        connection.request(
            method,
            _remove_token(target),
            body=body,
            headers=headers,
        )
        response = connection.getresponse()
        payload = response.read(_MAX_RESPONSE + 1)
        if len(payload) > _MAX_RESPONSE:
            raise MihomoProxyError("Mihomo dashboard response is too large")
    except (OSError, http.client.HTTPException) as exc:
        raise MihomoProxyError("Mihomo dashboard backend is unavailable") from exc
    finally:
        if connection is not None:
            connection.close()

    handler.send_response(response.status, response.reason)
    for key, value in response.getheaders():
        if key.lower() in _HOP_BY_HOP or key.lower() == "set-cookie":
            continue
        if key.lower() in {"content-type", "cache-control", "etag"}:
            handler.send_header(key, value)
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(payload)


def forward_websocket(handler, target: str, host: str, port: int) -> None:
    client = handler.connection
    upstream = None
    try:
        upstream = socket.create_connection((host, port), timeout=10)
        request_target = _remove_token(target)
        lines = [f"GET {request_target} HTTP/1.1"]
        for key, value in handler.headers.items():
            if key.lower() in _FORWARDED_REQUEST_HEADERS:
                lines.append(f"{key}: {value}")
        lines.append(f"Host: {host}:{port}")
        lines.append("Connection: Upgrade")
        lines.append("Upgrade: websocket")
        lines.append("")
        lines.append("")
        upstream.sendall("\r\n".join(lines).encode("iso-8859-1"))
        handshake = _read_headers(upstream)
        if not handshake.startswith(b"HTTP/1.1 101"):
            client.sendall(handshake)
            return
        client.sendall(handshake)
        handler.close_connection = True
        client.settimeout(None)
        upstream.settimeout(None)
        _relay(client, upstream)
    except (OSError, MihomoProxyError):
        try:
            client.sendall(
                b"HTTP/1.1 502 Bad Gateway\r\n"
                b"Content-Length: 0\r\n"
                b"Connection: close\r\n\r\n"
            )
        except OSError:
            pass
    finally:
        if upstream is not None:
            upstream.close()


def _request_body(handler) -> bytes | None:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise MihomoProxyError("Mihomo dashboard request body is invalid") from exc
    if length < 0 or length > _MAX_BODY:
        raise MihomoProxyError("Mihomo dashboard request body is too large")
    return handler.rfile.read(length) if length else None


def _read_headers(sock: socket.socket) -> bytes:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise MihomoProxyError("Mihomo WebSocket handshake closed")
        data.extend(chunk)
        if len(data) > 64 * 1024:
            raise MihomoProxyError("Mihomo WebSocket handshake is too large")
    return bytes(data)


def _relay(left: socket.socket, right: socket.socket) -> None:
    while True:
        readable, _, _ = select.select([left, right], [], [], 60)
        if not readable:
            continue
        for source in readable:
            payload = source.recv(64 * 1024)
            if not payload:
                return
            (right if source is left else left).sendall(payload)


def _remove_token(target: str) -> str:
    parsed = urlsplit(target)
    query = urlencode(
        [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
         if key != "token"],
    )
    return urlunsplit(("", "", parsed.path or "/", query, ""))


__all__ = ["MihomoProxyError", "forward_http", "forward_websocket"]
