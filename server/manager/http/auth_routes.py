"""Password login, registration policy, and Manager session cookies."""

from __future__ import annotations

import json
import sys
from urllib.parse import parse_qs

from server.manager.config import MANAGER_SESSION_TTL_SECONDS
from server.manager.http.responses import json_response
from server.manager.storage.control_db import ControlDatabaseError


class AuthenticationRoutesMixin:
    """Translate account authentication outcomes into HTTP sessions."""

    def _login(self) -> None:
        json_response(self, {"success": False, "error": "use Keycloak sign-in", "code": "keycloak_login_required"}, 410)

    def _oidc_redirect_uri(self) -> str:
        """Use the configured Manager origin, otherwise the trusted request origin."""
        from urllib.parse import urlsplit

        configured = str(getattr(self.state, "manager_public_endpoint", "") or "").strip().rstrip("/")
        if configured.startswith("https://"):
            return configured + "/auth/oidc/callback"
        origin = str(self._request_origin() or "").rstrip("/")
        parsed = urlsplit(origin)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("Manager callback origin is unavailable")
        return origin + "/auth/oidc/callback"

    def _oidc_login_start(self, parsed) -> None:
        from server.identity.auth_mode import auth_mode
        if auth_mode() != "keycloak":
            json_response(self, {"success": False, "error": "Keycloak login is unavailable"}, 503)
            return
        if not self._has_secure_ui_transport():
            json_response(self, {"success": False, "error": "Keycloak login requires a trusted HTTPS or private LAN origin"}, 400)
            return
        requested = parse_qs(parsed.query, keep_blank_values=True).get("next", ["/app"])[0]
        device_ticket = parse_qs(
            parsed.query, keep_blank_values=True,
        ).get("device_ticket", [""])[0]
        try:
            from server.identity.manager_oidc import start_login
            redirect_uri = self._oidc_redirect_uri()
            state, authorization_url = start_login(
                redirect_uri=redirect_uri, next_path=str(requested or "/app"),
                device_ticket=str(device_ticket or ""),
            )
        except (OSError, ValueError, TypeError) as exc:
            sys.stderr.write(f"[manager] Keycloak login is not configured: {type(exc).__name__}\n")
            json_response(self, {"success": False, "error": "Keycloak login is unavailable"}, 503)
            return
        secure = " Secure;" if self._is_secure_transport() else ""
        state_cookie = (
            f"tr-oidc-state={state}; Max-Age=600; HttpOnly; SameSite=Lax;"
            f"{secure} Path=/"
        )
        self._send_redirect(authorization_url, cookie=state_cookie)

    def _oidc_login_callback(self, parsed) -> None:
        import hmac
        query = parse_qs(parsed.query, keep_blank_values=True)
        if query.get("error"):
            secure = " Secure;" if self._is_secure_transport() else ""
            self._send_redirect("/app?auth_error=provider", cookie=(
                f"tr-oidc-state=; Max-Age=0; HttpOnly; SameSite=Lax;{secure} Path=/"
            ))
            return
        supplied_state = str(query.get("state", [""])[0])
        browser_state = self._cookie_value("tr-oidc-state")
        if not supplied_state or not browser_state or not hmac.compare_digest(
            supplied_state, browser_state,
        ):
            secure = " Secure;" if self._is_secure_transport() else ""
            self._send_redirect("/app?auth_error=invalid", cookie=(
                f"tr-oidc-state=; Max-Age=0; HttpOnly; SameSite=Lax;{secure} Path=/"
            ))
            return
        try:
            from server.identity.manager_oidc import finish_login
            token, session, next_path, device_ticket = finish_login(
                state=str(query.get("state", [""])[0]),
                code=str(query.get("code", [""])[0]),
                include_refresh=True,
            )
        except PermissionError:
            self._send_redirect("/app?auth_error=unverified", cookie=(
                self._session_cookie("", clear=True),
                self._refresh_cookie(""),
                self._oidc_state_cookie(clear=True),
            ))
            return
        except (OSError, ValueError, TypeError) as exc:
            sys.stderr.write(f"[manager] Keycloak callback rejected: {type(exc).__name__}\n")
            self._send_redirect("/app?auth_error=invalid", cookie=self._oidc_state_cookie(clear=True))
            return
        refresh = session.pop('_browser_refresh', {})
        from server.identity.server_admission import server_admission
        permitted, reason = server_admission(session, state=self.state)
        if not permitted:
            self._send_redirect(f"/app?auth_error={reason}", cookie=[
                self._session_cookie("", clear=True),
                self._refresh_cookie(""),
                self._oidc_state_cookie(clear=True),
            ])
            return
        if device_ticket:
            try:
                username, device_id, key_digest = self.state.device_challenges.consume_device_login_ticket(
                    device_ticket, origin=self._request_origin(),
                )
                if str(session.get("username") or "") != username:
                    raise PermissionError("device owner does not match Keycloak identity")
                from server.manager.domain.devices import device_public_key_digest
                from server.identity.keycloak_device import may_use_device
                binding = self.state.device_registry.key_binding(username=username, device_id=device_id)
                if (binding is None or not binding.get("enabled")
                        or device_public_key_digest(binding.get("public_key")) != key_digest
                        or not may_use_device(token=token, session=session, server_id=self.state.server_id,
                                              device_id=device_id, public_key=binding.get("public_key"))):
                    raise PermissionError("Keycloak did not authorize the verified device")
            except (ControlDatabaseError, OSError, RuntimeError, TypeError, ValueError, PermissionError) as exc:
                sys.stderr.write(f"[manager] device OIDC binding rejected: {type(exc).__name__}\n")
                self._send_redirect("/app?auth_error=device", cookie=[
                    self._session_cookie("", clear=True),
                    self._refresh_cookie(""),
                    self._oidc_state_cookie(clear=True),
                ])
                return
        from server.manager.config import MANAGER_SESSION_TTL_SECONDS
        try:
            lifetime = max(1, min(
                MANAGER_SESSION_TTL_SECONDS,
                int(session.get("expires_in") or MANAGER_SESSION_TTL_SECONDS),
            ))
        except (TypeError, ValueError):
            lifetime = MANAGER_SESSION_TTL_SECONDS
        self._send_redirect(
            next_path,
            cookie=[self._session_cookie(token, max_age=lifetime), self._oidc_state_cookie(clear=True),
                    self._refresh_cookie(str(refresh.get('refresh_token') or ''),
                                         max_age=int(refresh.get('refresh_expires_in') or 0))],
        )

    def _refresh_cookie(self, token: str, *, max_age: int = 0) -> str:
        secure = ' Secure;' if self._is_secure_transport() else ''
        lifetime = max(0, min(int(max_age), MANAGER_SESSION_TTL_SECONDS)) if token else 0
        return (f'tr-oidc-refresh={token}; Max-Age={lifetime}; HttpOnly; '
                f'SameSite=Lax;{secure} Path=/')

    def _oidc_state_cookie(self, *, clear: bool) -> str:
        secure = " Secure;" if self._is_secure_transport() else ""
        if clear:
            return f"tr-oidc-state=; Max-Age=0; HttpOnly; SameSite=Lax;{secure} Path=/"
        raise ValueError("state cookies are issued only by the OIDC start route")


    def _session_cookie(
        self, token: str, *, clear: bool = False,
        max_age: int = MANAGER_SESSION_TTL_SECONDS,
    ) -> str:
        secure = " Secure;" if self._is_secure_transport() else ""
        if clear:
            return (
                "ft-manager-session=; Max-Age=0; HttpOnly; SameSite=Lax;"
                f"{secure} Path=/"
            )
        return (
            f"ft-manager-session={token}; "
            f"Max-Age={max(1, min(int(max_age), MANAGER_SESSION_TTL_SECONDS))}; "
            f"HttpOnly; SameSite=Lax;{secure} Path=/"
        )
    def _register(self) -> None:
        json_response(self, {"success": False, "error": "account creation is managed by Keycloak administrators", "code": "keycloak_registration_required"}, 410)
