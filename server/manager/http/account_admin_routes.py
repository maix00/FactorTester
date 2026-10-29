"""Keycloak-managed identity administration entry point."""

from __future__ import annotations

from server.manager.http.responses import json_response


class AccountAdministrationRoutesMixin:
    """Retire Manager-local user, organization, and hierarchy CRUD."""

    @staticmethod
    def _keycloak_admin_console_url() -> str:
        from server.identity.manager_oidc import admin_console_url

        return admin_console_url()

    def _send_keycloak_identity_admin(self, *, retired: bool) -> None:
        context = getattr(self, "_identity_sync_admin_context", None)
        if callable(context):
            session, is_super, organization_paths = context()
        else:
            if not self._require_super_admin_session():
                return
            session, is_super, organization_paths = self._session(), True, set()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return
        if not is_super and not organization_paths:
            json_response(self, {
                "success": False,
                "error": "Keycloak identity administration permission required",
            }, 403)
            return
        try:
            console_url = self._keycloak_admin_console_url()
        except (OSError, RuntimeError, TypeError, ValueError):
            json_response(self, {
                "success": False,
                "code": "keycloak_admin_unavailable",
                "error": "Keycloak 管理控制台尚未配置",
            }, 503)
            return
        payload = {
            "success": True,
            "identity_provider": "keycloak",
            "managed_externally": True,
            "admin_scope": "realm" if is_super else "organization",
            "message": (
                "Users, organizations, groups, and role assignments are managed in Keycloak."
                if is_super else
                "Organization membership and scoped roles are managed in Keycloak FGAP."
            ),
            "admin_console_url": console_url,
        }
        if retired:
            payload.update({
                "success": False,
                "code": "keycloak_managed_identity",
                "error": "此本地用户管理接口已停用，请使用 Keycloak 管理控制台。",
            })
        json_response(self, payload, 410 if retired else 200)

    def _admin_account_directory(self) -> None:
        self._send_keycloak_identity_admin(retired=False)

    def _admin_create_user(self) -> None:
        self._send_keycloak_identity_admin(retired=True)

    def _admin_update_user(self) -> None:
        self._send_keycloak_identity_admin(retired=True)

    def _admin_create_organization(self) -> None:
        self._send_keycloak_identity_admin(retired=True)

    def _admin_create_level(self) -> None:
        self._send_keycloak_identity_admin(retired=True)

    def _admin_update_level(self) -> None:
        self._send_keycloak_identity_admin(retired=True)
