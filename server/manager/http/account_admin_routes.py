"""Keycloak-managed identity administration entry point."""

from __future__ import annotations

from server.manager.http.responses import json_response


class AccountAdministrationRoutesMixin:
    """Retire Manager-local user, organization, and hierarchy CRUD."""

    @staticmethod
    def _is_retired_local_identity_route(path: str) -> bool:
        """Prevent removed local-ACL APIs from falling through to service proxies."""
        return path == "/api/admin/access-control" or path.startswith(
            "/api/admin/access-control/"
        ) or path == "/api/admin/public-visitor-allowlist" or path.startswith(
            "/api/admin/public-visitor-allowlist/"
        )

    def _reject_retired_local_identity_route(self, parsed) -> bool:
        if not self._is_retired_local_identity_route(str(parsed.path)):
            return False
        json_response(self, {
            "success": False,
            "code": "keycloak_managed_identity",
            "error": "本地用户与权限接口已停用，请使用 Keycloak 管理身份与权限。",
        }, 410)
        return True

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
        delegated_role = ""
        if not is_super:
            from server.identity.realm_groups import administrative_group_role

            delegated_role = administrative_group_role(
                session.get("keycloak_groups", ())
            )
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
            "admin_scope": (
                "realm" if is_super else
                "organization" if delegated_role == "org_admin" else
                "level" if delegated_role == "level_admin" else
                "organization_or_level"
            ),
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

    def _admin_identity_users(self, parsed) -> None:
        """Return only Keycloak users inside the caller's signed admin scope."""
        from urllib.parse import parse_qs, urlparse

        from server.identity.keycloak_directory import users_in_admin_scope

        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return
        query = parse_qs(urlparse(self.path).query, keep_blank_values=True)
        try:
            result = users_in_admin_scope(
                groups=session.get("keycloak_groups", ()),
                roles=session.get("keycloak_roles", ()),
                query=query.get("query", [""])[0],
                limit=query.get("limit", [100])[0],
                offset=query.get("offset", [0])[0],
            )
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return
        except (TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        except Exception as exc:  # noqa: BLE001
            json_response(self, {
                "success": False,
                "code": "keycloak_directory_unavailable",
                "error": type(exc).__name__,
            }, 503)
            return
        # Expose only fields needed to choose an account for device management.
        # Stable identity IDs and complete group memberships remain server-side.
        users = [{
            key: row.get(key)
            for key in (
                "username", "alias", "organization_id", "organization_name",
                "level_id", "role", "active",
            )
        } for row in result["users"]]
        json_response(self, {
            "success": True,
            **{key: value for key, value in result.items() if key != "users"},
            "users": users,
            "identity_provider": "keycloak",
        }, headers={"Cache-Control": "private, no-store"})

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
