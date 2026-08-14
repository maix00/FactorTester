"""HTTP route adapters for device identity and Manager network information."""

from __future__ import annotations

import base64
import ipaddress
import json
import re
import sys
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse

from server.manager.config import MANAGER_SESSION_TTL_SECONDS
from server.manager.domain.device_clients import describe_client, observed_ip
from server.manager.domain.devices import (
    DeviceAuthorizationError,
    DeviceRegistryError,
    PUBLIC_DEVICE_LIMIT,
    PublicDeviceLimitError,
)
from server.manager.http.pages import (
    device_authorization_page,
    safe_login_next,
)
from server.manager.http.localization import preferred_locale
from server.manager.http.responses import json_response
from server.manager.storage.control_db import (
    ControlDatabaseError,
)


def device_authorization_endpoint(value: object) -> str:
    """Validate a public Manager base URL used in a one-time grant."""
    endpoint = str(value or "").strip().rstrip("/")
    parsed = urlparse(endpoint)
    if not endpoint or len(endpoint) > 512 or parsed.scheme not in {"http", "https"}:
        raise DeviceAuthorizationError(
            "target endpoint must be an http or https URL"
        )
    if not parsed.netloc or parsed.username or parsed.password:
        raise DeviceAuthorizationError("target endpoint must not contain credentials")
    if parsed.query or parsed.fragment:
        raise DeviceAuthorizationError(
            "target endpoint must not contain a query or fragment"
        )
    if parsed.scheme == "http":
        host = str(parsed.hostname or "").lower()
        try:
            local_http = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local_http = host in {"localhost", "127.0.0.1", "::1"}
        if not local_http:
            raise DeviceAuthorizationError(
                "public device authorization requires an HTTPS endpoint"
            )
    return endpoint


def device_handoff_url(
    target_origin: str,
    *,
    ticket: str,
    next_path: str,
) -> str:
    """Build a canonical-origin URL for a one-use authenticated handoff."""
    return (
        f"{str(target_origin or '').rstrip('/')}/device-handoff?"
        + urlencode({
            "ticket": str(ticket or ""),
            "next": str(next_path or "/"),
        })
    )


class DeviceNetworkRoutesMixin:
    """Route methods for device discovery and server endpoint presentation.

    ``runtime.Handler`` supplies the authentication/transport helpers and
    ``state`` attribute.  Keeping this as a Mixin is an incremental seam: the
    existing Handler remains the single dispatcher while this route family
    gains its own module and focused test surface.
    """

    state: Any

    def _device_request_metadata(self) -> dict[str, str]:
        client = describe_client(
            user_agent=self.headers.get("User-Agent", ""),
            client_hint=self.headers.get("X-FactorTester-Client", ""),
        )
        return {
            **client,
            "enrollment_ip": observed_ip(self._client_ip()),
        }

    def _device_public_targets(self) -> None:
        if self._session() is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return
        json_response(self, {
            "success": True,
            "source_server_id": self.state.server_id,
            "targets": self.state.public_device_targets(),
        }, headers={"Cache-Control": "no-store"})

    def _server_network_info(self) -> None:
        session = self._session()
        if (
            session is None
            and self._visitor_mode() is None
            and not self._is_private_lan_client()
        ):
            json_response(self, {"success": False, "error": "login required"}, 401)
            return
        host = self.headers.get("Host", "").strip()
        scheme = "https" if self._is_secure_transport() else "http"
        request_endpoint = f"{scheme}://{host}" if host else ""
        json_response(self, {
            "success": True,
            **self.state.server_network_info(request_endpoint=request_endpoint),
        }, headers={"Cache-Control": "no-store"})

    def _device_authorization_create(self) -> None:
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return
        if not self._has_secure_ui_transport():
            json_response(
                self,
                {
                    "success": False,
                    "error": (
                        "device authorization requires HTTPS outside private LAN"
                    ),
                },
                400,
            )
            return
        try:
            payload = self._json_body(16 * 1024)
            target_server_id = str(payload.get("target_server_id") or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", target_server_id):
                raise DeviceAuthorizationError("target_server_id is invalid")
            target_endpoint = device_authorization_endpoint(
                payload.get("target_endpoint")
            )
            next_path = safe_login_next(str(payload.get("next") or "/"))
            username = str(session.get("username") or "").strip()
            if not username:
                raise DeviceAuthorizationError("logged-in account is invalid")
            count = self.state.device_registry.public_device_count(username=username)
            if count >= PUBLIC_DEVICE_LIMIT:
                raise PublicDeviceLimitError(username=username, count=count)
            language = str(
                self.state.user_preferences.read(username).get("language")
                or "system"
            )
            if language == "system":
                language = preferred_locale(
                    self.headers.get("Accept-Language", "")
                )
            grant = self.state.device_authorizations.issue(
                username=username,
                target_server_id=target_server_id,
                target_endpoint=target_endpoint,
                device_name=str(payload.get("device_name") or ""),
                preferred_language=language,
            )
            query = urlencode({
                "token": str(grant["token"]),
                "next": next_path,
            })
            authorization_url = f"{target_endpoint}/device-authorize?{query}"
        except PublicDeviceLimitError as exc:
            json_response(self, {
                "success": False,
                "error": "public device limit reached",
                "code": "public_device_limit_reached",
                "public_device_count": exc.count,
                "public_device_limit": exc.limit,
            }, 409)
            return
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] device authorization failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "device authorization store is unavailable",
            }, 503)
            return
        except (
            DeviceAuthorizationError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {
            "success": True,
            "authorization_url": authorization_url,
            "target_server_id": target_server_id,
            "expires_in": grant["expires_in"],
            "backend": grant["backend"],
        }, headers={"Cache-Control": "no-store"})

    def _device_authorization_redeem(self) -> None:
        if not self.state.public_server:
            json_response(self, {
                "success": False,
                "error": (
                    "device authorization is available only on a public Manager"
                ),
            }, 404)
            return
        if not self._has_secure_ui_transport():
            json_response(self, {
                "success": False,
                "error": "device authorization requires HTTPS",
            }, 400)
            return
        try:
            payload = self._json_body(64 * 1024)
            authorization = self.state.device_authorizations.consume(
                payload.get("token"),
                target_server_id=self.state.server_id,
            )
            device = self.state.device_registry.enroll(
                username=str(authorization.get("username") or ""),
                device_id=str(payload.get("device_id") or ""),
                public_key=payload.get("public_key"),
                device_name=str(
                    payload.get("device_name")
                    or authorization.get("device_name")
                    or ""
                ),
                **self._device_request_metadata(),
            )
            token, principal, role = self.state.login_device(
                str(authorization.get("username") or ""),
            )
        except PublicDeviceLimitError as exc:
            json_response(self, {
                "success": False,
                "error": "public device limit reached",
                "code": "public_device_limit_reached",
                "public_device_count": exc.count,
                "public_device_limit": exc.limit,
            }, 409)
            return
        except ControlDatabaseError as exc:
            sys.stderr.write(
                f"[manager] device authorization redemption failed: {exc}\n"
            )
            json_response(self, {
                "success": False,
                "error": "device authorization store is unavailable",
            }, 503)
            return
        except (
            DeviceAuthorizationError,
            DeviceRegistryError,
            PermissionError,
            TypeError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
        ):
            json_response(self, {
                "success": False,
                "error": "device authorization is invalid or expired",
            }, 403)
            return
        json_response(self, {
            "success": True,
            "username": principal,
            "role": role,
            "capabilities": {
                "manager": role == "super_admin",
                "research": True,
            },
            "token": token,
            "expires_in": MANAGER_SESSION_TTL_SECONDS,
            "device_id": device.get("device_id"),
        }, headers={
            "Set-Cookie": self._session_cookie(token),
            "Cache-Control": "no-store",
        })

    def _device_authorization_page(self, parsed: Any) -> None:
        query = parse_qs(parsed.query, keep_blank_values=True)
        token = query.get("token", [""])[0]
        next_path = query.get("next", ["/"])[0]
        language = self.headers.get("Accept-Language", "")
        try:
            authorization = self.state.device_authorizations.preview(
                token, target_server_id=self.state.server_id,
            )
            snapshot = str(
                authorization.get("preferred_language") or "system"
            )
            if snapshot != "system":
                language = snapshot
        except (ControlDatabaseError, DeviceAuthorizationError):
            # Keep the public page generic for invalid/expired grants.  The
            # one-time token is authoritatively checked again on redemption.
            pass
        self._send_html(device_authorization_page(
            token,
            next_path,
            accept_language=language,
        ))

    def _device_handoff(self, parsed: Any) -> None:
        """Redeem a device session ticket on the canonical public origin."""
        target_origin = str(
            getattr(self.state, "manager_public_endpoint", "") or ""
        ).strip().rstrip("/")
        current_origin = self._request_origin()
        next_path = safe_login_next(
            str(parse_qs(parsed.query, keep_blank_values=True).get(
                "next", ["/"]
            )[0] or "/")
        )
        ticket = parse_qs(parsed.query, keep_blank_values=True).get(
            "ticket", [""]
        )[0]
        if (
            not self.state.public_server
            or not target_origin
            or current_origin != target_origin
            or not self._has_secure_ui_transport()
        ):
            self._send_redirect(
                "/compliance?next=" + quote(next_path, safe="/?=&%")
            )
            return
        try:
            token, _principal, _role = self.state.redeem_device_handoff(
                ticket,
                target_origin=target_origin,
            )
        except (PermissionError, TypeError, ValueError):
            self._send_redirect(
                "/compliance?next=" + quote(next_path, safe="/?=&%")
            )
            return
        self._send_redirect(
            next_path,
            cookie=self._session_cookie(token),
        )

    def _device_list(self) -> None:
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return
        owner = (
            ""
            if str(session.get("role") or "") == "super_admin"
            else str(session["username"])
        )
        try:
            devices = self.state.device_registry.list(
                username=owner,
                include_disabled=True,
            )
            public_device_count = self.state.device_registry.public_device_count(
                username=owner,
            )
            public_user_count = (
                (1 if public_device_count else 0)
                if owner
                else self.state.device_registry.public_user_count()
            )
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] device list failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "device registry is unavailable",
            }, 503)
            return
        json_response(self, {
            "success": True,
            "devices": devices,
            "public_device_count": public_device_count,
            "public_user_count": public_user_count,
            "public_device_limit": PUBLIC_DEVICE_LIMIT,
            "server_id": self.state.server_id,
            **self.state.device_registry.backend_status(),
        })

    def _device_summary(self) -> None:
        session = self._session()
        owner = ""
        scope = "server"
        if session is not None and str(session.get("role") or "") != "super_admin":
            owner = str(session.get("username") or "")
            scope = "account"
        try:
            count = self.state.device_registry.public_device_count(username=owner)
            user_count = (
                (1 if count else 0)
                if owner
                else self.state.device_registry.public_user_count()
            )
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] device summary failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "device registry is unavailable",
            }, 503)
            return
        json_response(self, {
            "success": True,
            "public_device_count": count,
            "public_user_count": user_count,
            "public_device_limit": PUBLIC_DEVICE_LIMIT,
            "scope": scope,
            **self.state.device_registry.backend_status(),
        }, headers={"Cache-Control": "no-store"})

    def _device_enroll(self) -> None:
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return
        if not self._has_secure_ui_transport():
            json_response(self, {
                "success": False,
                "error": "device enrollment requires HTTPS outside private LAN",
            }, 400)
            return
        try:
            payload = self._json_body(64 * 1024)
            device = self.state.device_registry.enroll(
                username=str(session["username"]),
                device_id=str(payload.get("device_id") or ""),
                public_key=payload.get("public_key"),
                device_name=str(payload.get("device_name") or ""),
                **self._device_request_metadata(),
            )
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] device enrollment failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "device registry is unavailable",
            }, 503)
            return
        except PublicDeviceLimitError as exc:
            json_response(self, {
                "success": False,
                "code": "public_device_limit_reached",
                "error": str(exc),
                "public_device_count": exc.count,
                "public_device_limit": exc.limit,
            }, 409)
            return
        except (DeviceRegistryError, TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {
            "success": True,
            "device": device,
            "sync": self.state.device_registry.backend_status(),
        }, 201)

    def _device_revoke(self) -> None:
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return
        try:
            payload = self._json_body(16 * 1024)
            device_id = str(payload.get("device_id") or "")
            admin = str(session.get("role") or "") == "super_admin"
            records = self.state.device_registry.list(
                username="" if admin else str(session["username"]),
                include_disabled=True,
            )
            record = next(
                (item for item in records if item.get("device_id") == device_id),
                None,
            )
            if record is None:
                raise PermissionError("device was not found")
            device = self.state.device_registry.revoke(device_id)
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] device revoke failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "device registry is unavailable",
            }, 503)
            return
        except (DeviceRegistryError, TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {
            "success": True,
            "device": device,
            "sync": self.state.device_registry.backend_status(),
        })

    def _device_challenge(self) -> None:
        if not self._has_secure_ui_transport():
            json_response(self, {
                "success": False,
                "error": "HTTPS is required for device authentication",
            }, 400)
            return
        challenge_id, challenge = self.state.device_challenges.issue()
        json_response(self, {
            "success": True,
            "challenge_id": challenge_id,
            "challenge": base64.urlsafe_b64encode(challenge).decode("ascii").rstrip("="),
            "expires_in": int(self.state.device_challenges.ttl_seconds),
        }, headers={"Cache-Control": "no-store"})

    def _device_verify(self) -> None:
        if not self._has_secure_ui_transport():
            json_response(self, {
                "success": False,
                "error": "HTTPS is required for device authentication",
            }, 400)
            return
        try:
            payload = self._json_body(64 * 1024)
            challenge = self.state.device_challenges.consume(
                payload.get("challenge_id"),
            )
            record = self.state.device_registry.verify(
                device_id=str(payload.get("device_id") or ""),
                public_key=payload.get("public_key"),
                challenge=challenge,
                signature=payload.get("signature"),
                last_seen_ip=observed_ip(self._client_ip()),
            )
            token, principal, role = self.state.login_device(
                str(record.get("username") or ""),
            )
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] device verification failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "device registry is unavailable",
            }, 503)
            return
        except (
            DeviceRegistryError,
            PermissionError,
            TypeError,
            ValueError,
            KeyError,
        ) as exc:
            sys.stderr.write(
                f"[manager] device verification rejected: {type(exc).__name__}\n"
            )
            json_response(self, {
                "success": False,
                "error": "device is not approved",
            }, 403)
            return
        handoff_url = ""
        target_origin = str(
            getattr(self.state, "manager_public_endpoint", "") or ""
        ).strip().rstrip("/")
        if (
            target_origin
            and self._request_origin() != target_origin
            and self._visitor_entry_origin_allowed()
        ):
            next_path = safe_login_next(str(payload.get("next") or "/"))
            ticket = self.state.issue_device_handoff(
                principal,
                role,
                target_origin=target_origin,
            )
            handoff_url = device_handoff_url(
                target_origin,
                ticket=ticket,
                next_path=next_path,
            )
        json_response(self, {
            "success": True,
            "username": principal,
            "role": role,
            "capabilities": {
                "manager": role == "super_admin",
                "research": True,
            },
            "token": token,
            "expires_in": MANAGER_SESSION_TTL_SECONDS,
            "device_id": record.get("device_id"),
            "handoff_url": handoff_url,
        }, headers={"Set-Cookie": self._session_cookie(token)})
