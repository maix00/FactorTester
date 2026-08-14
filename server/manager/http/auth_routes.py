"""Password login, registration policy, and Manager session cookies."""

from __future__ import annotations

import json
import sys

from server.manager.config import MANAGER_SESSION_TTL_SECONDS
from server.manager.http.pages import (
    PUBLIC_DEVICE_COMPLIANCE_NOTICE,
    PUBLIC_REGISTRATION_NOTICE,
)
from server.manager.http.responses import json_response
from server.manager.storage.control_db import ControlDatabaseError


class AuthenticationRoutesMixin:
    """Translate account authentication outcomes into HTTP sessions."""
    def _json_body(self, maximum: int) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > maximum:
            raise ValueError("request body is invalid")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def _login(self) -> None:
        if self._visitor_mode() is not None:
            json_response(
                self,
                {
                    "success": False,
                    "error": "访客模式不能登录，请先离开访客模式。",
                    "code": "visitor_login_forbidden",
                    "redirect": "/compliance?next=/",
                },
                403,
            )
            return
        if self.state.require_device_auth and not self._is_loopback_client():
            json_response(self, {
                "success": False,
                "error": "device authentication required",
            }, 403)
            return
        if not self._has_secure_ui_transport():
            json_response(self, {
                "success": False,
                "error": "login requires HTTPS outside private LAN",
            }, 400)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 16 * 1024:
            json_response(self, {
                "success": False,
                "error": "invalid login request",
            }, 400)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            token, principal, role = self.state.login(
                str(payload.get("username") or ""),
                str(payload.get("password") or ""),
            )
        except (ValueError, TypeError, json.JSONDecodeError):
            json_response(self, {
                "success": False,
                "error": "invalid login request",
            }, 400)
            return
        except PermissionError as exc:
            json_response(self, {
                "success": False,
                "error": str(exc),
            }, 403)
            return
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] login authority unavailable: {exc}\n")
            json_response(self, {
                "success": False,
                "code": "control_database_unavailable",
                "error": "control database is unavailable and no usable local account is available",
            }, 503)
            return
        except Exception as exc:
            sys.stderr.write(f"[manager] login failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "manager login failed",
            }, 500)
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
        }, headers={"Set-Cookie": self._session_cookie(token)})

    def _session_cookie(self, token: str, *, clear: bool = False) -> str:
        secure = " Secure;" if self._is_secure_transport() else ""
        if clear:
            return (
                "ft-manager-session=; Max-Age=0; HttpOnly; SameSite=Lax;"
                f"{secure} Path=/"
            )
        return (
            f"ft-manager-session={token}; "
            f"Max-Age={MANAGER_SESSION_TTL_SECONDS}; "
            f"HttpOnly; SameSite=Lax;{secure} Path=/"
        )
    def _register(self) -> None:
        if self.state.require_device_auth and not self._is_loopback_client():
            json_response(self, {
                "success": False,
                "error": PUBLIC_DEVICE_COMPLIANCE_NOTICE,
                "code": "public_device_auth_required",
            }, 403)
            return
        if not self.state.public_registration_enabled:
            json_response(self, {
                "success": False,
                "error": PUBLIC_REGISTRATION_NOTICE,
                "code": "public_registration_disabled",
            }, 403)
            return
        if not self._has_secure_ui_transport():
            json_response(self, {"success": False, "error": "registration requires HTTPS outside private LAN"}, 400)
            return
        try:
            payload = self._json_body(16 * 1024)
            principal, role, alias, organization_id = self.state.register(
                str(payload.get("username") or payload.get("alias") or ""),
                str(payload.get("password") or ""),
                str(payload.get("organization_id") or ""),
            )
            token = self.state.login(principal, str(payload.get("password") or ""))[0]
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] account registration unavailable: {exc}\n")
            json_response(self, {
                "success": False,
                "code": "control_database_unavailable",
                "error": "local account database is unavailable; registration cannot be queued",
            }, 503)
            return
        json_response(
            self,
            {"success": True, "token": token, "username": principal, "alias": alias, "role": role, "organization_id": organization_id, "capabilities": {"manager": role == "super_admin", "research": True}},
            headers={"Set-Cookie": self._session_cookie(token)},
        )
