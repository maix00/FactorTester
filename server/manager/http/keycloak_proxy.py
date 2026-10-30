"""Same-origin, realm-scoped reverse proxy for the Manager's Keycloak.

The proxy exists so browsers can use the configured Keycloak issuer under the
Manager origin (including deployments whose TLS certificate is an IP SAN).
It is deliberately not a general-purpose proxy: the destination is fixed by
deployment configuration and only the configured realm and its static assets
are reachable.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import os
import re
import ssl
from urllib.parse import urlsplit


KEYCLOAK_PREFIX = "/identity"
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"})
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "host",
    "content-length", "forwarded", "x-forwarded-for", "x-forwarded-host",
    "x-forwarded-port", "x-forwarded-proto", "x-forwarded-server",
})
_REALM_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class _InvalidProxyRequest(ValueError):
    """The caller supplied an invalid or unsupported proxy request body."""


def _realm() -> str:
    from server.identity.user_session import oidc_settings

    realm = str(oidc_settings().get("realm") or "")
    if not _REALM_RE.fullmatch(realm):
        raise ValueError("invalid Keycloak realm")
    return realm


def _backend_url() -> str:
    """Return a fixed private Keycloak origin; never accept a request host."""
    from server import branding

    value = str(
        os.environ.get("TR_KEYCLOAK_PROXY_BACKEND_URL")
        or branding.env("KEYCLOAK_PROXY_BACKEND_URL")
        or ""
    ).strip()
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("invalid private Keycloak proxy backend")
    if parsed.scheme == "http":
        host = parsed.hostname.lower()
        try:
            address = ipaddress.ip_address(host)
            private = address.is_private or address.is_loopback or address.is_link_local
        except ValueError:
            private = "." not in host or host.endswith((".internal", ".local"))
        if not private:
            raise ValueError("plain HTTP Keycloak backend must be private")
    return value.rstrip("/")


def _allowed_path(path: str, realm: str) -> bool:
    """Limit access to public OIDC routes and this realm's Admin Console."""
    if (
        not path.startswith(KEYCLOAK_PREFIX + "/")
        or "\\" in path
        or any(part in {".", ".."} for part in path.split("/"))
        or re.search(r"%2f|%5c|%2e", path, flags=re.IGNORECASE)
    ):
        return False
    relative = path[len(KEYCLOAK_PREFIX) + 1 :]
    if relative == "resources" or relative.startswith("resources/"):
        return True
    if relative == f"realms/{realm}" or relative.startswith(f"realms/{realm}/"):
        return True
    if relative == f"admin/{realm}/console" or relative.startswith(
        f"admin/{realm}/console/"
    ):
        return True
    if relative == f"admin/realms/{realm}" or relative.startswith(
        f"admin/realms/{realm}/"
    ):
        return True
    return False


def _public_origin(handler) -> tuple[str, str, int | None]:
    """Resolve only the deployment's canonical Manager origin."""
    configured = str(
        getattr(getattr(handler, "state", None), "manager_public_endpoint", "")
        or ""
    ).strip().rstrip("/")
    parsed = urlsplit(configured)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        if not handler._is_secure_transport():
            raise ValueError("canonical Manager origin is not configured")
        host = str(handler.headers.get("Host") or "").strip()
        parsed = urlsplit("https://" + host)
        if not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("invalid Manager request origin")
    return parsed.scheme, parsed.netloc, parsed.port


def _request_body(handler) -> bytes:
    transfer_encoding = str(handler.headers.get("Transfer-Encoding") or "").strip()
    if transfer_encoding:
        raise _InvalidProxyRequest("chunked request bodies are not supported")
    raw_length = str(handler.headers.get("Content-Length") or "0").strip()
    if not raw_length.isdecimal():
        raise _InvalidProxyRequest("invalid request length")
    length = int(raw_length)
    if length > MAX_REQUEST_BYTES:
        raise OverflowError("Keycloak request body exceeds the configured limit")
    body = handler.rfile.read(length) if length else b""
    if len(body) != length:
        raise _InvalidProxyRequest("incomplete request body")
    return body


def _connection(parsed, timeout: float):
    if parsed.scheme == "https":
        return http.client.HTTPSConnection(
            parsed.hostname, parsed.port or 443, timeout=timeout,
            context=ssl.create_default_context(),
        )
    return http.client.HTTPConnection(
        parsed.hostname, parsed.port or 80, timeout=timeout,
    )


class KeycloakProxyRoutesMixin:
    """Expose only the configured realm through the same Manager origin."""

    def _proxy_keycloak(self, parsed, *, method: str, head_only: bool = False) -> bool:
        path = str(getattr(parsed, "path", "") or "")
        if not path.startswith(KEYCLOAK_PREFIX):
            return False
        response_started = False
        connection = None
        try:
            realm = _realm()
            if not _allowed_path(path, realm):
                self.send_error(404)
                return True
            if method not in _METHODS:
                self.send_error(405)
                return True
            backend = urlsplit(_backend_url())
            body = b"" if method in {"GET", "HEAD"} else _request_body(self)
            scheme, public_netloc, public_port = _public_origin(self)
            headers = {}
            for name, value in self.headers.items():
                lower = name.lower()
                if lower in _HOP_BY_HOP or lower.startswith("x-forwarded-"):
                    continue
                headers[name] = value
            headers["Host"] = backend.netloc
            headers["X-Forwarded-Host"] = public_netloc
            headers["X-Forwarded-Proto"] = scheme
            if public_port is not None:
                headers["X-Forwarded-Port"] = str(public_port)
            try:
                headers["X-Forwarded-For"] = str(self._client_ip())
            except (AttributeError, ValueError):
                headers.pop("X-Forwarded-For", None)

            connection = _connection(backend, timeout=15.0)
            request_target = path + ("?" + parsed.query if parsed.query else "")
            connection.request(method, request_target, body=body or None, headers=headers)
            response = connection.getresponse()
            length_text = response.getheader("Content-Length")
            length = None
            if length_text is not None:
                if not length_text.isdecimal():
                    raise ValueError("invalid Keycloak response length")
                length = int(length_text)
                if length > MAX_RESPONSE_BYTES:
                    self.send_error(502, "Keycloak response exceeds proxy limit")
                    return True

            self.send_response(response.status, response.reason)
            response_started = True
            connection_header = response.getheader("Connection", "")
            connection_tokens = {
                item.strip().lower() for item in connection_header.split(",") if item.strip()
            }
            copied_length = False
            for name, value in response.getheaders():
                lower = name.lower()
                if lower in _HOP_BY_HOP or lower in connection_tokens:
                    continue
                if lower == "location":
                    value = self._rewrite_internal_keycloak_location(
                        value, backend, scheme, public_netloc,
                    )
                self.send_header(name, value)
                copied_length = copied_length or lower == "content-length"
            if length is None and response.status not in {204, 304}:
                # The Manager's HTTP/1.1 handler uses close-delimited bodies
                # when Content-Length is absent; stream without buffering.
                self.send_header("Connection", "close")
                self.close_connection = True
            elif length is not None and not copied_length:
                self.send_header("Content-Length", str(length))
            self.end_headers()
            if not head_only and method != "HEAD" and response.status not in {204, 304}:
                transferred = 0
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    transferred += len(chunk)
                    if transferred > MAX_RESPONSE_BYTES:
                        self.close_connection = True
                        break
                    self.wfile.write(chunk)
            connection.close()
        except OverflowError:
            if not response_started:
                self.send_error(413, "Keycloak request body exceeds proxy limit")
        except _InvalidProxyRequest as exc:
            if response_started:
                self.close_connection = True
            else:
                self.send_error(400, str(exc))
        except (OSError, ssl.SSLError, http.client.HTTPException, ValueError, TypeError):
            if response_started:
                # Once response headers have been sent, a second status line
                # would corrupt the stream. Close it so the browser discards
                # the incomplete Keycloak document.
                self.close_connection = True
            else:
                try:
                    self.send_error(503, "Keycloak identity service unavailable")
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
        finally:
            if connection is not None:
                connection.close()
        return True

    @staticmethod
    def _rewrite_internal_keycloak_location(value, backend, scheme, public_netloc):
        """Prevent a private backend origin from escaping in redirects."""
        location = str(value or "")
        parsed = urlsplit(location)
        if parsed.scheme and parsed.netloc == backend.netloc:
            return f"{scheme}://{public_netloc}{parsed.path}" + (
                ("?" + parsed.query) if parsed.query else ""
            ) + (("#" + parsed.fragment) if parsed.fragment else "")
        return location


def proxy_backend_configured() -> bool:
    try:
        _backend_url()
        _realm()
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    return True
