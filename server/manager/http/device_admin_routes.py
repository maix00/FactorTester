"""Keycloak-scoped administration for Manager device records."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from server.identity.realm_groups import (
    administrative_group_role,
    managed_member_group_paths,
)
from server.manager.http.responses import json_response
from server.manager.storage.control_db import ControlDatabaseError


class DeviceAdministrationRoutesMixin:
    """Expose bounded per-user device views using verified Keycloak groups.

    Device records remain Manager-local operational state.  Keycloak is the
    authority for who may inspect or revoke them; usernames are only used to
    locate the existing device rows after that authorization succeeds.
    """

    state: object

    def _device_admin_context(
        self,
    ) -> tuple[dict[str, object] | None, bool, set[str]]:
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return None, False, set()
        if not self._has_secure_ui_transport():
            json_response(self, {
                "success": False,
                "error": "device administration requires a secure Manager connection",
            }, 400)
            return None, False, set()
        roles = session.get("keycloak_roles") or ()
        is_super = (
            isinstance(roles, (tuple, list, set, frozenset))
            and "admin_console:manage" in roles
        )
        groups = session.get("keycloak_groups") or ()
        scopes = managed_member_group_paths(groups)
        if not is_super and administrative_group_role(tuple(groups)) not in {
            "org_admin", "level_admin",
        }:
            json_response(self, {
                "success": False,
                "error": "Keycloak device administration permission required",
            }, 403)
            return None, False, set()
        return session, is_super, scopes

    def _admin_device_target_allowed(
        self, *, username: str, scopes: set[str],
    ) -> bool:
        from server.identity.federation_identity_sync import (
            manager_keycloak_admin_adapter,
        )

        adapter = manager_keycloak_admin_adapter()
        user_id = adapter.user_id(username)
        paths = adapter.user_group_paths(
            user_id, page_size=100, max_groups=2000,
        )
        return any(
            path == scope or path.startswith(scope + "/")
            for path in paths
            for scope in scopes
        )

    def _admin_device_list(self) -> None:
        _session, is_super, scopes = self._device_admin_context()
        if _session is None:
            return
        username = str(
            parse_qs(urlparse(self.path).query, keep_blank_values=True)
            .get("username", [""])[0]
        ).strip()
        if not username or len(username) > 256:
            json_response(self, {
                "success": False,
                "code": "device_username_required",
                "error": "select one user to view registered devices",
            }, 400)
            return
        if not is_super:
            try:
                allowed = self._admin_device_target_allowed(
                    username=username, scopes=scopes,
                )
            except LookupError:
                json_response(self, {
                    "success": False,
                    "error": "user was not found in the authorized Keycloak scope",
                }, 404)
                return
            except Exception:
                json_response(self, {
                    "success": False,
                    "code": "keycloak_authorization_unavailable",
                    "error": "Keycloak authorization is unavailable",
                }, 503)
                return
            if not allowed:
                json_response(self, {
                    "success": False,
                    "error": "user is outside the administrator's Keycloak group scope",
                }, 403)
                return
        try:
            devices = self.state.device_registry.list(
                username=username, include_disabled=True,
            )
            total = self.state.device_registry.public_device_total_count(
                username=username,
            )
        except ControlDatabaseError:
            json_response(self, {
                "success": False,
                "error": "device registry is unavailable",
            }, 503)
            return
        json_response(self, {
            "success": True,
            "username": username,
            "devices": devices,
            "public_device_count": total,
            "public_device_total_count": total,
            "public_user_count": 1 if total else 0,
            "scope": "realm" if is_super else "keycloak-group",
            **self.state.device_registry.backend_status(),
        }, headers={"Cache-Control": "private, no-store"})

    def _admin_device_revoke(self) -> None:
        session, is_super, scopes = self._device_admin_context()
        if session is None:
            return
        try:
            payload = self._json_body(16 * 1024)
            username = str(payload.get("username") or "").strip()
            device_id = str(payload.get("device_id") or "").strip()
            if not username or len(username) > 256 or not device_id:
                raise ValueError("username and device_id are required")
            if not is_super and not self._admin_device_target_allowed(
                username=username, scopes=scopes,
            ):
                raise PermissionError(
                    "user is outside the administrator's Keycloak group scope"
                )
            records = self.state.device_registry.list(
                username=username, include_disabled=True,
            )
            record = next(
                (item for item in records if item.get("device_id") == device_id),
                None,
            )
            if record is None:
                raise PermissionError("device was not found for this user")
            device = self.state.device_registry.revoke(device_id)
        except LookupError:
            json_response(self, {
                "success": False,
                "error": "user was not found in the authorized Keycloak scope",
            }, 404)
            return
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return
        except ControlDatabaseError:
            json_response(self, {
                "success": False,
                "error": "device registry is unavailable",
            }, 503)
            return
        except Exception as exc:
            from server.manager.domain.devices import DeviceRegistryError

            if isinstance(exc, (DeviceRegistryError, TypeError, ValueError)):
                json_response(self, {"success": False, "error": str(exc)}, 400)
            else:
                json_response(self, {
                    "success": False,
                    "code": "keycloak_authorization_unavailable",
                    "error": "Keycloak authorization is unavailable",
                }, 503)
            return
        json_response(self, {
            "success": True,
            "device": device,
            "sync": self.state.device_registry.backend_status(),
        }, headers={"Cache-Control": "private, no-store"})
