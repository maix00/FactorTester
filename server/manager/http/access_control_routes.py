"""Super-admin account, visitor-policy, and device administration routes."""

from __future__ import annotations

import sys
from typing import Any

from server.manager.http.responses import json_response
from server.manager.storage.control_db import ControlDatabaseError


class AccessControlRoutesMixin:
    """Expose one central-control projection for the User and organization UI."""

    state: Any

    def _access_control_store(self) -> Any | None:
        store = getattr(self.state, "control_store", None)
        if store is None:
            json_response(self, {
                "success": False,
                "error": "central control database is not configured",
            }, 503)
            return None
        return store

    @staticmethod
    def _safe_account(account: dict[str, object]) -> dict[str, object]:
        """Project account metadata without password material."""
        return {
            key: account.get(key)
            for key in (
                "username", "alias", "role", "is_admin", "is_developer",
                "organization_id", "organization_name", "level_id",
                "parent_username", "active", "created_at", "updated_at",
            )
            if key in account
        }

    def _admin_access_control(self) -> None:
        if not self._require_super_admin_session():
            return
        store = self._access_control_store()
        if store is None:
            return
        try:
            users = [
                self._safe_account(dict(item))
                for item in store.admin_account_directory()
            ]
            allowlist = store.list_public_visitor_allowlist(
                server_id=self.state.server_id,
                include_disabled=True,
            )
            devices = self.state.device_registry.list(include_disabled=True)
        except (ControlDatabaseError, OSError, RuntimeError, TypeError, ValueError) as exc:
            sys.stderr.write(f"[manager] access-control read failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "central access-control data is unavailable",
            }, 503)
            return
        json_response(self, {
            "success": True,
            "server_id": self.state.server_id,
            "server_role": self.state.server_role,
            "control_database": {
                "backend": "postgresql",
                "authoritative": True,
                "synchronized_across_managers": True,
            },
            "users": users,
            "visitor_allowlist": allowlist,
            "devices": devices,
        }, headers={"Cache-Control": "no-store"})

    def _admin_add_visitor_allowlist(self) -> None:
        if not self._require_super_admin_session():
            return
        store = self._access_control_store()
        if store is None:
            return
        try:
            payload = self._json_body(32 * 1024)
            target_server = str(payload.get("server_id") or self.state.server_id).strip()
            if target_server != str(self.state.server_id):
                raise ValueError("visitor policy can only be changed on the current server")
            value = store.add_public_visitor_allowlist(
                server_id=target_server,
                username=str(payload.get("username") or "").strip(),
                created_by=str(self._session()["username"]),
            )
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] access-control allowlist add failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "central access-control data is unavailable",
            }, 503)
            return
        except (TypeError, ValueError, OSError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {"success": True, "entry": value}, 201)

    def _admin_remove_visitor_allowlist(self) -> None:
        if not self._require_super_admin_session():
            return
        store = self._access_control_store()
        if store is None:
            return
        try:
            payload = self._json_body(32 * 1024)
            target_server = str(payload.get("server_id") or self.state.server_id).strip()
            if target_server != str(self.state.server_id):
                raise ValueError("visitor policy can only be changed on the current server")
            value = store.remove_public_visitor_allowlist(
                server_id=target_server,
                username=str(payload.get("username") or "").strip(),
            )
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] access-control allowlist remove failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "central access-control data is unavailable",
            }, 503)
            return
        except (TypeError, ValueError, OSError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        if value is None:
            json_response(self, {"success": False, "error": "visitor allowlist entry was not found"}, 404)
            return
        json_response(self, {"success": True, "entry": value})

    def _admin_revoke_device(self) -> None:
        if not self._require_super_admin_session():
            return
        store = self._access_control_store()
        if store is None:
            return
        try:
            payload = self._json_body(16 * 1024)
            device_id = str(payload.get("device_id") or "").strip()
            if not device_id:
                raise ValueError("device_id is required")
            device = self.state.device_registry.revoke(device_id)
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] access-control device revoke failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "central access-control data is unavailable",
            }, 503)
            return
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return
        except (TypeError, ValueError, OSError, RuntimeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {"success": True, "device": device})
