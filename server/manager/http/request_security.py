"""HTTP transport, session extraction, and public-entry access policy."""

from __future__ import annotations

import hmac
import ipaddress
from urllib.parse import parse_qs, quote

from server.manager.http.pages import (
    compliance_page as manager_compliance_page,
    login_page as manager_login_page,
    safe_login_next as manager_safe_login_next,
)
from server.manager.http.responses import json_response


MANAGER_ACTION_PATHS = frozenset({
    "/vibe/start",
    "/vibe/stop",
    "/start",
    "/stop",
    "/restart-api",
    "/restart-bundle",
    "/force-stop",
})


class RequestSecurityMixin:
    """Define the public/private HTTP boundary before route dispatch."""
    def _client_ip(self) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
        peer = ipaddress.ip_address(self.client_address[0])
        if not peer.is_loopback:
            return peer
        forwarded = self.headers.get(
            "X-Forwarded-For", ""
        ).split(",", 1)[0].strip()
        if not forwarded:
            return peer
        try:
            return ipaddress.ip_address(forwarded)
        except ValueError:
            return peer

    def _is_loopback_client(self) -> bool:
        return self._client_ip().is_loopback

    def _is_private_lan_client(self) -> bool:
        client = self._client_ip()
        return client.is_private or client.is_link_local

    def _is_https_proxy_request(self) -> bool:
        try:
            peer = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        forwarded_proto = self.headers.get(
            "X-Forwarded-Proto", ""
        ).split(",", 1)[0].strip().lower()
        return peer.is_loopback and forwarded_proto == "https"

    def _is_direct_https_request(self) -> bool:
        """Whether this Manager socket itself is serving authenticated TLS."""
        return bool(getattr(self.server, "tls_enabled", False))

    def _is_secure_transport(self) -> bool:
        return self._is_direct_https_request() or self._is_https_proxy_request()

    def _has_secure_ui_transport(self) -> bool:
        return (
            self._is_direct_https_request()
            or
            self._is_loopback_client()
            or self._is_private_lan_client()
            or self._is_https_proxy_request()
        )
    def _is_same_origin_browser_action(self) -> bool:
        if not self._is_loopback_client():
            return False
        origin = self.headers.get("Origin", "").rstrip("/")
        host = self.headers.get("Host", "").strip()
        return bool(origin and host and origin == f"http://{host}")

    def _has_capability(self) -> bool:
        supplied = self._bearer_token()
        return (
            bool(supplied)
            and hmac.compare_digest(supplied, self.state.capability_token())
        )

    def _bearer_token(self) -> str:
        scheme, _, supplied = self.headers.get("Authorization", "").partition(" ")
        if scheme.lower() == "bearer" and supplied:
            return supplied.strip()
        # Embedded documentation/database pages are ordinary browser
        # navigations and cannot attach the SPA Authorization header.  The
        # Manager login cookie is HttpOnly and is therefore only parsed here.
        for item in self.headers.get("Cookie", "").split(";"):
            name, separator, value = item.strip().partition("=")
            if separator and name == "ft-manager-session":
                return value.strip()
        return ""

    def _session(self) -> dict[str, object] | None:
        return self.state.session(self._bearer_token())

    def _serve_login_page(self, parsed) -> None:
        requested = parse_qs(parsed.query, keep_blank_values=True).get(
            "next", ["/"]
        )[0]
        if self.state.require_device_auth and not self._is_loopback_client():
            self._serve_compliance_page(str(requested or "/"))
            return
        body = manager_login_page(
            str(requested or "/"),
            accept_language=self.headers.get("Accept-Language", ""),
        )
        self._send_html(body)

    def _send_html(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; form-action 'self'; base-uri 'none'; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'",
        )
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_compliance_page(self, next_path: str = "/") -> None:
        body = manager_compliance_page(
            next_path,
            accept_language=self.headers.get("Accept-Language", ""),
        )
        self._send_html(body)

    def _public_login_gate(self, parsed, *, method: str) -> bool:
        """Apply the instance-level public UI policy before route dispatch."""
        if not self.state.require_login_for_ui:
            # The local Manager deliberately keeps its existing unauthenticated
            # panel behavior.  Route-specific APIs still enforce their own
            # user or capability checks below.
            return True

        path = parsed.path
        if path == "/compliance":
            return True

        if path == "/device-authorize":
            if not self.state.public_server:
                json_response(self, {
                    "success": False,
                    "error": "device authorization is available only on a public Manager",
                }, 404)
                return False
            if not self._has_secure_ui_transport():
                json_response(self, {
                    "success": False,
                    "error": "device authorization requires HTTPS",
                }, 400)
                return False
            return True

        if path == "/api/device/authorization/redeem":
            if not self.state.public_server:
                json_response(self, {
                    "success": False,
                    "error": "device authorization is available only on a public Manager",
                }, 404)
                return False
            if not self._has_secure_ui_transport():
                json_response(self, {
                    "success": False,
                    "error": "device authorization requires HTTPS",
                }, 400)
                return False
            return True

        if method == "GET" and path == "/api/device/summary":
            # The compliance page may show an aggregate count before the
            # browser has a session.  It contains no usernames or device IDs.
            return True

        if method == "GET" and path == "/api/server/network-info":
            # The local home page may display the Manager-provided LAN
            # address before login.  A public endpoint still needs a session;
            # the route itself repeats this distinction as defence in depth.
            if self._is_private_lan_client():
                return True

        if path in {"/api/device/challenge", "/api/device/verify"}:
            if not self._has_secure_ui_transport():
                json_response(
                    self,
                    {
                        "success": False,
                        "error": "HTTPS is required for device authentication",
                    },
                    400,
                )
                return False
            return True

        if path == "/login":
            return True

        # Signed client release files are distribution artifacts, not an
        # interactive user interface.  They must remain downloadable before a
        # client has a session so an existing FTClient can update itself.
        if method == "GET" and path.startswith("/api/client/releases/"):
            return True

        machine_request = (
            path.startswith("/api/federation/")
            or path == "/api/worktrees"
            or path in MANAGER_ACTION_PATHS
        )
        if machine_request:
            if not self._has_secure_ui_transport():
                json_response(
                    self,
                    {
                        "success": False,
                        "error": "HTTPS is required for public Manager communication",
                    },
                    400,
                )
                return False
            # Federation handlers validate their endpoint-specific machine
            # token.  We only keep them outside the browser login redirect so
            # an authenticated peer can continue to operate normally.
            if path.startswith("/api/federation/"):
                return True
            if self._has_capability():
                return True

        session = self._session()
        if session is not None and self._has_secure_ui_transport():
            return True

        if path.startswith("/api/") or method != "GET":
            status = 400 if not self._has_secure_ui_transport() else 401
            headers = (
                {}
                if status == 400
                else {"WWW-Authenticate": "Bearer"}
            )
            json_response(
                self,
                {
                    "success": False,
                    "error": (
                        "HTTPS is required for public Manager access"
                        if status == 400
                        else (
                            "device authentication required"
                            if self.state.require_device_auth
                            else "login required"
                        )
                    ),
                },
                status,
                headers=headers,
            )
            return False

        requested = path + (f"?{parsed.query}" if parsed.query else "")
        destination = "/compliance?next=" if self.state.require_device_auth else "/login?next="
        location = destination + quote(
            manager_safe_login_next(requested), safe="/?=&%"
        )
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _authorization_bearer(self) -> str:
        scheme, _, supplied = self.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer":
            return ""
        return supplied.strip()

    def _has_federation_registration_token(self) -> bool:
        expected = self.state.federation_registration_token
        supplied = self._authorization_bearer()
        return bool(expected and supplied and hmac.compare_digest(supplied, expected))

    def _has_federation_proxy_token(self) -> bool:
        supplied = self._authorization_bearer()
        return bool(
            supplied
            and hmac.compare_digest(supplied, self.state.federation_proxy_token())
        )
