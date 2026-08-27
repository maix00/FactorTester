"""HTTP transport, session extraction, and public-entry access policy."""

from __future__ import annotations

import hmac
import ipaddress
import os
import socket
import ssl
from urllib.parse import parse_qs, quote, urlsplit

from server.manager.http.pages import (
    compliance_page as manager_compliance_page,
)
from server.manager.http.pages import (
    login_page as manager_login_page,
)
from server.manager.http.pages import (
    safe_login_next as manager_safe_login_next,
)
from server.manager.http.responses import json_response
from server.manager.http.visitor_access import (
    CLIENT_ACCESS_COOKIE,
    VISITOR_COOKIE,
    VisitorMode,
    client_access_cookie,
    normalize_visitor_id,
    request_origin,
    target_compliance_url,
    target_visitor_url,
    visitor_cookie,
)
from server.manager.network_endpoints import client_endpoint_for_port
from server.manager.services.network_info import local_internal_addresses

MANAGER_ACTION_PATHS = frozenset({
    "/vibe/start",
    "/vibe/stop",
    "/start",
    "/stop",
    "/restart-api",
    "/restart-bundle",
    "/force-stop",
    # A public Manager keeps this control-plane route behind the same
    # loopback/capability boundary as the other operator actions.  Without
    # listing it here, the public login gate rejects the Manager capability
    # before the release route can issue its short-lived 7997 upload ticket.
    "/api/client/releases/beta/upload-access",
})

CLIENT_ACCESS_HEADER = "X-FactorTester-Client-Access"
CLIENT_ACCESS_VALUE = "ftclient"
VISITOR_ID_HEADER = "X-FactorTester-Visitor-ID"

class RequestSecurityMixin:
    """Define the public/private HTTP boundary before route dispatch."""

    def setup(self) -> None:
        """Negotiate TLS per worker when this listener also accepts HTTP."""
        if getattr(self.server, "tls_accepts_plain_http", False):
            raw_connection = self.request
            previous_timeout = raw_connection.gettimeout()
            try:
                raw_connection.settimeout(5)
                if raw_connection.recv(1, socket.MSG_PEEK) == b"\x16":
                    self.request = self.server.tls_context.wrap_socket(
                        raw_connection,
                        server_side=True,
                    )
            finally:
                try:
                    self.request.settimeout(previous_timeout)
                except OSError:
                    # A failed TLS handshake may already have closed the
                    # accepted socket; do not mask the original error.
                    pass
        super().setup()

    def _peer_ip(self) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
        return ipaddress.ip_address(self.client_address[0])

    def _is_trusted_proxy_peer(self) -> bool:
        peer = self._peer_ip()
        if peer.is_loopback:
            return True
        networks = getattr(
            getattr(self, "state", None), "trusted_proxy_networks", (),
        )
        return any(peer in network for network in networks)

    def _single_forwarded_value(self, name: str) -> str:
        value = str(self.headers.get(name, "") or "").strip()
        # This Manager supports one explicitly trusted proxy hop.  Reject a
        # chain rather than selecting a caller-controlled first/last value.
        if not value or "," in value:
            return ""
        return value

    def _client_ip(self) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
        peer = self._peer_ip()
        if not self._is_trusted_proxy_peer():
            return peer
        forwarded = self._single_forwarded_value("X-Forwarded-For")
        if not forwarded:
            return peer
        try:
            return ipaddress.ip_address(forwarded)
        except ValueError:
            return peer

    def _is_loopback_client(self) -> bool:
        return self._client_ip().is_loopback

    def _is_local_ftclient(self) -> bool:
        """Accept the host FTClient through an explicitly trusted Docker gateway."""
        if self._is_loopback_client():
            return True
        if getattr(getattr(self, "state", None), "public_server", False):
            return False
        if self.headers.get("X-FactorTester-Client", "").strip().lower() != "cli":
            return False
        client = self._client_ip()
        networks = getattr(getattr(self, "state", None), "local_client_networks", ())
        return any(client in network for network in networks)

    def _is_private_lan_client(self) -> bool:
        client = self._client_ip()
        return client.is_private or client.is_link_local

    def _is_https_proxy_request(self) -> bool:
        try:
            trusted = self._is_trusted_proxy_peer()
        except ValueError:
            return False
        forwarded_proto = self._single_forwarded_value(
            "X-Forwarded-Proto",
        ).lower()
        return trusted and forwarded_proto == "https"

    def _is_direct_https_request(self) -> bool:
        """Whether this Manager socket itself is serving authenticated TLS."""
        if getattr(self.server, "tls_accepts_plain_http", False):
            return isinstance(getattr(self, "connection", None), ssl.SSLSocket)
        return bool(getattr(self.server, "tls_enabled", False))

    def _https_redirect_origin(self) -> str:
        configured = os.environ.get(
            "FACTORTESTER_MANAGER_PUBLIC_ENDPOINT", ""
        ).strip()
        candidates = [configured, f"https://{self.headers.get('Host', '').strip()}"]
        for candidate in candidates:
            if not candidate:
                continue
            try:
                parsed = urlsplit(candidate)
                parsed.port
            except ValueError:
                continue
            if (
                parsed.scheme == "https"
                and parsed.hostname
                and parsed.username is None
                and parsed.password is None
            ):
                return f"https://{parsed.netloc}"
        host, port = self.server.server_address[:2]
        host = str(host)
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"https://{host}:{port}"

    def _redirect_plain_http_to_https(self) -> bool:
        """Redirect HTTP accepted by a mixed Manager listener before dispatch."""
        if not getattr(self.server, "tls_accepts_plain_http", False):
            return False
        if self._is_direct_https_request():
            return False
        # A server-side Profile Agent talks to the colocated Manager through
        # loopback/Docker-private networking. Redirecting it to the public
        # endpoint would turn an internal catalog read into paid egress.
        if self._is_local_agent_request():
            return False
        request_target = self.path if self.path.startswith("/") else "/"
        self.send_response(308)
        self.send_header(
            "Location",
            f"{self._https_redirect_origin()}{request_target}",
        )
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

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

    def _is_local_agent_request(self) -> bool:
        """Recognize a Manager-issued Profile Agent on a local network path."""
        if self.headers.get("X-FactorTester-Agent", "").strip().lower() != "profile":
            return False
        if not (self._is_loopback_client() or self._is_private_lan_client()):
            return False
        matcher = getattr(getattr(self, "state", None), "agent_session_matches", None)
        if not callable(matcher):
            return False
        return bool(
            matcher(
                self._bearer_token(),
                self.headers.get("X-FactorTester-Agent-Profile", ""),
                self.headers.get("X-FactorTester-Agent-Claim", ""),
            )
        )

    def _is_swift_network_discovery_request(self) -> bool:
        """Allow only the native client to read pre-login node addresses.

        The endpoint contains no account, device, or task data, but it is
        needed before Swift can choose the first public Manager.  Keep the
        exception narrow: a browser (or an arbitrary API caller) must still
        pass the normal public login/visitor gate.
        """
        return (
            self.headers.get("X-FactorTester-Client", "").strip().lower()
            == "swift"
            and self._has_secure_ui_transport()
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

    def _cookie_value(self, name: str) -> str:
        for item in self.headers.get("Cookie", "").split(";"):
            key, separator, value = item.strip().partition("=")
            if separator and key == name:
                return value.strip()
        return ""

    def _client_access_header_allowed(self) -> bool:
        """Recognize the public, non-privileged native-client entry marker."""
        return (
            getattr(self.state, "require_login_for_ui", False)
            and getattr(self.state, "public_server", False)
            and self._has_secure_ui_transport()
            and self.headers.get(CLIENT_ACCESS_HEADER, "").strip().lower()
            == CLIENT_ACCESS_VALUE
        )

    def _client_access_allowed(self) -> bool:
        """Return whether this request may display the native client entry.

        The marker is intentionally only a presentation/access-policy signal;
        it never bypasses account, device, or Manager authentication.
        """
        if self._client_access_header_allowed():
            return True
        if not (
            getattr(self.state, "require_login_for_ui", False)
            and getattr(self.state, "public_server", False)
        ):
            return False
        origin = self._request_origin()
        token = self._cookie_value(CLIENT_ACCESS_COOKIE)
        store = getattr(self.state, "visitor_access", None)
        return bool(
            origin
            and token
            and store is not None
            and store.valid_client_access(token, target_origin=origin)
        )

    def _issue_client_access_cookie(self) -> str:
        """Persist a native-client marker across the WebView navigation."""
        if not self._client_access_header_allowed():
            return ""
        current_origin = self._request_origin()
        target_origin = self._visitor_redirect_target()
        store = getattr(self.state, "visitor_access", None)
        if not (
            store is not None
            and target_origin
            and current_origin == target_origin
        ):
            return ""
        visitor_id = ""
        if self._client_access_header_allowed():
            visitor_id = normalize_visitor_id(
                self.headers.get(VISITOR_ID_HEADER, "")
            )
        token = store.issue_client_access(
            target_origin,
            visitor_id=visitor_id,
        )
        return client_access_cookie(token, secure=True)

    def _request_origin(self) -> str:
        scheme = (
            "https"
            if self._is_https_proxy_request() or self._is_direct_https_request()
            else "http"
        )
        return request_origin(
            scheme=scheme,
            host=self.headers.get("Host", ""),
        )

    def _client_data_endpoint_for_request(self) -> str:
        """Return the browser-reachable sibling of this Manager request.

        Control requests and byte transfers intentionally use separate ports,
        but they must use the same client-visible host.  In particular, never
        return a WireGuard address to a browser that opened the Manager via
        loopback or a LAN address.
        """
        config = getattr(self.state, "data_plane_process_config", None)
        if config is None:
            return ""
        configured = str(config.client_data_endpoint or "").strip().rstrip("/")
        if not configured:
            return ""
        requested = self._request_origin()
        try:
            requested_host = str(urlsplit(requested).hostname or "").lower()
            configured_control_host = str(
                urlsplit(config.client_control_endpoint).hostname or ""
            ).lower()
            configured_data_host = str(
                urlsplit(configured).hostname or ""
            ).lower()
        except ValueError:
            return configured
        if not requested_host:
            return configured
        allowed_hosts = {
            configured_control_host,
            configured_data_host,
            "127.0.0.1",
            "localhost",
            "::1",
        }
        if not getattr(self.state, "public_server", False):
            allowed_hosts.update(
                str(value).strip().lower()
                for value in local_internal_addresses()
                if str(value).strip()
            )
        if requested_host not in allowed_hosts:
            return configured
        try:
            return client_endpoint_for_port(
                requested,
                int(config.client_port),
                name="client data endpoint",
            )
        except ValueError:
            return configured

    def _rewrite_client_data_access(self, access):
        """Keep a 7997 ticket on the same host as its 7998 issuer."""
        if not isinstance(access, dict):
            return access
        endpoint = self._client_data_endpoint_for_request()
        path = str(access.get("path") or "")
        if not endpoint or not path.startswith("/"):
            return access
        rewritten = dict(access)
        rewritten["data_endpoint"] = endpoint
        rewritten["url"] = endpoint.rstrip("/") + path
        return rewritten

    def _visitor_mode(self) -> VisitorMode | None:
        """Return the public anonymous capability set for this origin.

        An account session always takes precedence over the anonymous visitor
        cookie.  The login response expires that cookie, but a browser can
        retain a stale/duplicate cookie while processing the response (or
        replay it during the first post-login requests).  Letting that cookie
        continue to classify an already authenticated request as a visitor
        would hide the account's private catalogs, profiles, and full job
        history.  A valid session is the authoritative signal here; once it
        expires, the remaining visitor cookie naturally falls back to the
        bounded anonymous capability.
        """
        if not (
            getattr(self.state, "require_login_for_ui", False)
            and getattr(self.state, "public_server", False)
        ):
            return None
        if self._session() is not None:
            return None
        origin = self._request_origin()
        token = self._cookie_value(VISITOR_COOKIE)
        store = getattr(self.state, "visitor_access", None)
        if not origin or not token or store is None:
            return None
        visitor_id = store.visitor_id_for_session(
            token,
            target_origin=origin,
        )
        if not visitor_id:
            return None
        return VisitorMode(visitor_id=visitor_id)

    def _anonymous_ui_allowed(self) -> bool:
        return (
            not self.state.require_login_for_ui
            or self._visitor_mode() is not None
        )

    def _visitor_entry_origin_allowed(self) -> bool:
        return (
            self._request_origin() in tuple(
                getattr(self.state, "visitor_entry_origins", ())
            )
            or self._client_access_allowed()
        )

    def _visitor_redirect_target(self) -> str:
        target = str(
            getattr(self.state, "manager_public_endpoint", "") or ""
        ).strip()
        return target if target.startswith("https://") else ""

    def _redirect_configured_ingress(self, parsed, *, next_path: str) -> bool:
        """Move an ingress navigation to the canonical public IP origin.

        The grant only authorizes the target compliance page to display the
        existing visitor entry.  It does not create a visitor session; that
        still requires an explicit click on the visitor link.
        """
        current_origin = self._request_origin()
        target_origin = self._visitor_redirect_target()
        store = getattr(self.state, "visitor_access", None)
        if not (
            store is not None
            and target_origin
            and current_origin in tuple(
                getattr(self.state, "visitor_entry_origins", ())
            )
            and current_origin != target_origin
        ):
            return False
        grant = store.issue_grant(target_origin)
        self._send_redirect(
            target_compliance_url(
                target_origin,
                grant=grant,
                next_path=manager_safe_login_next(next_path),
            )
        )
        return True

    def _send_redirect(self, location: str, *, cookie: str = "") -> None:
        self.send_response(303)
        self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _serve_visitor_entry(self, parsed) -> None:
        requested = parse_qs(parsed.query, keep_blank_values=True).get(
            "next", ["/"]
        )[0]
        next_path = manager_safe_login_next(str(requested or "/"))
        current_origin = self._request_origin()
        target_origin = self._visitor_redirect_target()
        store = getattr(self.state, "visitor_access", None)

        if (
            store is not None
            and target_origin
            and current_origin in tuple(
                getattr(self.state, "visitor_entry_origins", ())
            )
        ):
            grant = store.issue_grant(target_origin)
            self._send_redirect(
                target_visitor_url(
                    target_origin,
                    grant=grant,
                    next_path=next_path,
                )
            )
            return

        if store is not None and current_origin == target_origin:
            grant = parse_qs(parsed.query, keep_blank_values=True).get(
                "grant", [""]
            )[0]
            token = store.redeem_grant(grant, target_origin=target_origin)
            if token:
                self._send_redirect(
                    next_path,
                    cookie=visitor_cookie(token, secure=True),
                )
                return

            if self._client_access_allowed():
                client_access_token = self._cookie_value(CLIENT_ACCESS_COOKIE)
                visitor_id = store.client_access_visitor_id(
                    client_access_token,
                    target_origin=target_origin,
                )
                if not visitor_id and self._client_access_header_allowed():
                    visitor_id = normalize_visitor_id(
                        self.headers.get(VISITOR_ID_HEADER, "")
                    )
                self._send_redirect(
                    next_path,
                    cookie=visitor_cookie(
                        store.issue_session(
                            target_origin,
                            visitor_id=visitor_id,
                        ),
                        secure=True,
                    ),
                )
                return

        self._send_redirect(
            "/compliance?next=" + quote(next_path, safe="/?=&%")
        )

    def _session(self) -> dict[str, object] | None:
        return self.state.session(self._bearer_token())

    def _serve_login_page(self, parsed) -> None:
        requested = parse_qs(parsed.query, keep_blank_values=True).get(
            "next", ["/"]
        )[0]
        if self.state.require_device_auth and not self._is_loopback_client():
            self._serve_compliance_page(
                str(requested or "/"),
                show_visitor_entry=(
                    self._visitor_mode() is None
                    and self._visitor_entry_origin_allowed()
                ),
            )
            return
        body = manager_login_page(
            str(requested or "/"),
            accept_language=self.headers.get("Accept-Language", ""),
        )
        self._send_html(body)

    def _send_html(self, body: bytes, *, cookie: str = "") -> None:
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
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_compliance_page(
        self,
        next_path: str = "/",
        *,
        show_visitor_entry: bool | None = None,
        visitor_grant: str = "",
    ) -> None:
        if show_visitor_entry is None:
            show_visitor_entry = (
                self._visitor_mode() is None
                and self._visitor_entry_origin_allowed()
            )
        visitor_grant = str(visitor_grant or "").strip()
        current_origin = self._request_origin()
        target_origin = self._visitor_redirect_target()
        store = getattr(self.state, "visitor_access", None)
        grant_is_valid = bool(
            visitor_grant
            and self._visitor_mode() is None
            and store is not None
            and current_origin == target_origin
            and store.valid_grant(
                visitor_grant,
                target_origin=target_origin,
            )
        )
        client_access_cookie = self._issue_client_access_cookie()
        show_visitor_entry = bool(
            show_visitor_entry
            or grant_is_valid
            or self._client_access_allowed()
            or bool(client_access_cookie)
        )
        visitor_entry_href = ""
        if show_visitor_entry:
            safe_next = quote(
                manager_safe_login_next(next_path),
                safe="/?=&%",
            )
            if grant_is_valid:
                visitor_entry_href = (
                    "/visitor?grant="
                    + quote(visitor_grant, safe="")
                    + "&next="
                    + safe_next
                )
            else:
                visitor_entry_href = "/visitor?next=" + safe_next
        body = manager_compliance_page(
            next_path,
            accept_language=self.headers.get("Accept-Language", ""),
            visitor_entry_href=visitor_entry_href,
        )
        self._send_html(body, cookie=client_access_cookie)

    def _public_login_gate(self, parsed, *, method: str) -> bool:
        """Apply the instance-level public UI policy before route dispatch."""
        if not self.state.require_login_for_ui:
            # The local Manager deliberately keeps its existing unauthenticated
            # panel behavior.  Route-specific APIs still enforce their own
            # user or capability checks below.
            return True

        if self._visitor_mode() is not None:
            # The visitor capability intentionally reuses the local
            # unauthenticated route behavior.  Route handlers still enforce
            # their own session/capability checks for private and mutating
            # operations.
            return True

        path = parsed.path
        if path == "/compliance":
            return True

        if method == "GET" and path == "/api/device/summary":
            # The compliance page may show an aggregate count before the
            # browser has a session.  It contains no usernames or device IDs.
            return True

        if method == "GET" and path == "/api/server/network-info":
            # The local home page may display the Manager-provided LAN
            # and public-node summary in visitor mode as well as on a LAN.
            # The route itself repeats this distinction as defence in depth.
            if (
                self._is_private_lan_client()
                or self._visitor_mode() is not None
                or self._is_swift_network_discovery_request()
            ):
                return True

        if path in {"/api/device/challenge", "/api/device/verify"}:
            target_origin = self._visitor_redirect_target()
            if (
                self.state.public_server
                and target_origin
                and self._request_origin() != target_origin
            ):
                json_response(self, {
                    "success": False,
                    "error": "device authentication is available only on the public IP origin",
                }, 403)
                return False
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

        # Published technical documentation is intentionally public.  The
        # catalog exposes curated Markdown only, never the repository tree.
        if method == "GET" and (
            path == "/docs"
            or path.startswith("/docs/")
            or path == "/api/docs/index"
            or path.startswith("/api/docs/pages/")
        ):
            return True

        if method == "GET" and not path.startswith("/api/"):
            requested = path + (f"?{parsed.query}" if parsed.query else "")
            if self._redirect_configured_ingress(
                parsed,
                next_path=requested,
            ):
                return False

        # Signed client release files are distribution artifacts, not an
        # interactive user interface.  They must remain downloadable before a
        # client has a session so an existing FTClient can update itself.
        if method == "GET" and path.startswith("/api/client/releases/"):
            return True

        if method == "GET":
            from server.manager.http.research_graph_catalog_routes import (
                is_public_research_graph_catalog_read,
            )

            if is_public_research_graph_catalog_read(path):
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
        device_gate_required = (
            self.state.require_device_auth
            and not self._is_loopback_client()
        )
        local_agent = self._is_local_agent_request()
        if (
            session is not None
            and self._has_secure_ui_transport()
            and (
                not device_gate_required
                or local_agent
                or self.state.session_allows_device_origin(
                    self._bearer_token(),
                    self._request_origin(),
                )
            )
        ):
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
        client_access_cookie = self._issue_client_access_cookie()
        self.send_response(303)
        self.send_header("Location", location)
        if client_access_cookie:
            self.send_header("Set-Cookie", client_access_cookie)
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
