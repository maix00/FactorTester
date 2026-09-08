"""HTTP route adapters for device identity and Manager network information."""

from __future__ import annotations

import base64
import json
import sys
from typing import Any

from server.manager.config import MANAGER_SESSION_TTL_SECONDS
from server.manager.domain.device_clients import describe_client, observed_ip
from server.manager.domain.devices import (
    DeviceRegistryError,
)
from server.manager.http.responses import json_response
from server.manager.storage.control_db import (
    ControlDatabaseError,
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

    def _server_network_info(self) -> None:
        session = self._session()
        if (
            session is None
            and self._visitor_mode() is None
            and not self._is_private_lan_client()
            and not self._is_swift_network_discovery_request()
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

    def _device_list(self) -> None:
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return
        # Personal settings always use account scope, including super admins.
        # Server-wide administration has dedicated /api/admin/access-control APIs.
        owner = str(session["username"])
        try:
            devices = self.state.device_registry.list(
                username=owner,
                include_disabled=True,
            )
            public_device_total_count = self.state.device_registry.public_device_total_count(
                username=owner,
            )
            public_user_count = (
                (1 if public_device_total_count else 0)
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
            "public_device_count": public_device_total_count,
            "public_device_total_count": public_device_total_count,
            "public_user_count": public_user_count,
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
            total_count = self.state.device_registry.public_device_total_count(
                username=owner,
            )
            user_count = (
                (1 if total_count else 0)
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
            "public_device_count": total_count,
            "public_device_total_count": total_count,
            "public_user_count": user_count,
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
        if not self._is_allowlisted_visitor_session(session):
            json_response(self, {
                "success": False,
                "error": (
                    "device enrollment is available only after public allowlist "
                    "visitor login"
                ),
            }, 403)
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
        except (DeviceRegistryError, TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {
            "success": True,
            "device": device,
            "sync": self.state.device_registry.backend_status(),
        }, 201)

    def _is_allowlisted_visitor_session(self, session: dict[str, object]) -> bool:
        """Allow enrollment only for a live public allowlist visitor session.

        The browser cannot select an enrollment policy. The server derives
        permission from the private session authentication method and a fresh
        allowlist check, so an internal or ordinary password session cannot
        manufacture a device record.
        """
        if not bool(getattr(self.state, "public_server", False)):
            return False
        reader = getattr(self.state, "session_authentication", None)
        if not callable(reader) or reader(self._bearer_token()) != "visitor-password":
            return False
        try:
            return self.state.public_visitor_login_account(
                str(session.get("username") or "")
            ) is not None
        except ControlDatabaseError:
            return False

    def _device_revoke(self) -> None:
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return
        try:
            payload = self._json_body(16 * 1024)
            device_id = str(payload.get("device_id") or "")
            records = self.state.device_registry.list(
                username=str(session["username"]),
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
                origin=self._request_origin(),
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
        session = self.state.session(token) or {}
        json_response(self, {
            "success": True,
            "username": principal,
            "alias": session.get("alias") or principal,
            "role": role,
            "capabilities": {
                "manager": role == "super_admin",
                "research": True,
            },
            "token": token,
            "expires_in": MANAGER_SESSION_TTL_SECONDS,
            "device_id": record.get("device_id"),
        }, headers={"Set-Cookie": self._session_cookie(token)})
