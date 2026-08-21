"""Central account, organization, and hierarchy administration."""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable, Mapping
from typing import Any

from server.manager.domain.organization_scope import (
    normalize_organization_id,
    validate_alias,
)
from server.manager.storage.local_accounts import LocalAccountStore
from tools.data.account_manage import (
    DEFAULT_ORGANIZATION_ID,
    DEFAULT_ORGANIZATION_NAME,
    ROLE_DEVELOPER,
    ROLE_LEVEL_ADMIN,
    ROLE_ORG_ADMIN,
    ROLE_SUPER_ADMIN,
    ROLE_USER,
    ensure_root_levels,
    hash_password,
    normalize_accounts,
    normalize_levels,
    normalize_organization,
    root_level_id_for_org,
    slugify_org_id,
)
from tools.data.sqlite.account_manager.user import save_accounts
from tools.data.sqlite.account_manager.user_level import (
    save_levels,
    save_organizations,
)

ROLE_LABELS = {
    ROLE_SUPER_ADMIN: "超级管理员",
    ROLE_ORG_ADMIN: "机构管理员",
    ROLE_LEVEL_ADMIN: "层级管理员",
    ROLE_DEVELOPER: "开发人员",
    ROLE_USER: "普通用户",
}
ALLOWED_ROLES = frozenset(ROLE_LABELS)


class AccountAdministrationError(ValueError):
    """A safe, user-facing account administration validation error."""


class AccountAdministrationService:
    """Operate on the central directory and refresh the local SQLite mirror."""

    def __init__(
        self,
        store: object,
        *,
        profile_initializer: Callable[[str], object] | None = None,
    ) -> None:
        self.store = store
        self.profile_initializer = profile_initializer

    def snapshot(self) -> dict[str, Any]:
        organizations = self._organizations()
        levels = self._levels(organizations)
        users = [
            self.safe_account(dict(item))
            for item in self.store.admin_account_directory()
        ]
        return {
            "users": users,
            "organizations": organizations,
            "levels": levels,
            "role_labels": dict(ROLE_LABELS),
            "default_organization_id": DEFAULT_ORGANIZATION_ID,
        }

    @staticmethod
    def safe_account(account: Mapping[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in (
            "username", "alias", "role", "is_admin", "is_developer",
            "organization_id", "organization_name", "level_id",
            "parent_username", "active", "created_at", "updated_at",
        ):
            if key not in account:
                continue
            result[key] = AccountAdministrationService._json_value(
                account.get(key)
            )
        return result

    @staticmethod
    def _json_value(value: Any) -> Any:
        """Convert database temporal values before passing them to json.dumps."""
        return value.isoformat() if hasattr(value, "isoformat") else value

    def create_user(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        alias = validate_alias(payload.get("alias"))
        password = str(payload.get("password") or "")
        if len(password) < 6:
            raise AccountAdministrationError("密码至少6位")
        role = str(payload.get("role") or ROLE_USER).strip()
        if role not in ALLOWED_ROLES:
            raise AccountAdministrationError("不能创建该角色")

        organizations = self._organizations()
        organization_id = str(
            payload.get("organization_id") or DEFAULT_ORGANIZATION_ID
        ).strip()
        organization = self._organization(organizations, organization_id)
        if organization is None:
            raise AccountAdministrationError("机构不存在")
        levels = self._levels(organizations)
        level_id = str(payload.get("level_id") or "").strip()
        if not level_id:
            level_id = root_level_id_for_org(organization_id)
        level = self._level(levels, level_id)
        if level is None or self._level_org(level) != organization_id:
            raise AccountAdministrationError("层级不存在或不属于目标机构")

        accounts = normalize_accounts(self.store.load_accounts())
        parent_username = str(payload.get("parent_username") or "").strip()
        self._validate_parent(
            parent_username, "", organization_id, accounts,
        )
        username = LocalAccountStore.unique_registration_username(
            organization_id, alias, accounts,
        )
        salt = secrets.token_hex(16)
        account = {
            "username": username,
            "alias": alias,
            "salt": salt,
            "hash": hash_password(password, salt),
            "role": role,
            "is_admin": role == ROLE_SUPER_ADMIN,
            "is_developer": role == ROLE_DEVELOPER,
            "organization_id": organization_id,
            "organization_name": str(organization.get("name") or ""),
            "level_id": level_id,
            "parent_username": parent_username,
            "active": True,
        }
        self.store.create_account(account)
        accounts.append(account)
        self._mirror_accounts(accounts)
        if self.profile_initializer is not None:
            try:
                self.profile_initializer(username)
            except (
                AttributeError, ConnectionError, OSError, RuntimeError,
                TypeError, ValueError,
            ):
                pass
        return self.safe_account(account)

    def update_user(
        self,
        username: str,
        payload: Mapping[str, Any],
        *,
        current_username: str = "",
    ) -> dict[str, Any]:
        target_username = str(username or "").strip()
        accounts = normalize_accounts(self.store.load_accounts())
        target = next(
            (item for item in accounts if item.get("username") == target_username),
            None,
        )
        if target is None:
            raise AccountAdministrationError("用户不存在")
        if target_username == str(current_username or "").strip() and "role" in payload:
            requested_role = str(payload.get("role") or "").strip()
            if requested_role != ROLE_SUPER_ADMIN:
                raise AccountAdministrationError("不能在当前会话中降级当前超级管理员")

        organizations = self._organizations()
        organization_id = str(
            payload.get("organization_id")
            or target.get("organization_id")
            or DEFAULT_ORGANIZATION_ID
        ).strip()
        organization = self._organization(organizations, organization_id)
        if organization is None:
            raise AccountAdministrationError("机构不存在")
        levels = self._levels(organizations)
        level_id = str(
            payload.get("level_id") or target.get("level_id") or ""
        ).strip() or root_level_id_for_org(organization_id)
        level = self._level(levels, level_id)
        if level is None or self._level_org(level) != organization_id:
            raise AccountAdministrationError("层级不存在或与用户机构不一致")

        if "role" in payload:
            role = str(payload.get("role") or "").strip()
            if role not in ALLOWED_ROLES:
                raise AccountAdministrationError("不能设置该角色")
            target["role"] = role
            target["is_admin"] = role == ROLE_SUPER_ADMIN
            target["is_developer"] = role == ROLE_DEVELOPER
        target["organization_id"] = organization_id
        target["organization_name"] = str(organization.get("name") or "")
        target["level_id"] = level_id

        if "parent_username" in payload:
            parent_username = str(payload.get("parent_username") or "").strip()
            self._validate_parent(
                parent_username, target_username, organization_id, accounts,
            )
            target["parent_username"] = parent_username
        if payload.get("password"):
            password = str(payload.get("password"))
            if len(password) < 6:
                raise AccountAdministrationError("密码至少6位")
            salt = secrets.token_hex(16)
            target["salt"] = salt
            target["hash"] = hash_password(password, salt)

        self.store.replace_accounts(accounts)
        self._mirror_accounts(accounts)
        return self.safe_account(target)

    def create_organization(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise AccountAdministrationError("机构名称不能为空")
        raw_id = str(payload.get("id") or "").strip() or slugify_org_id(name)
        try:
            organization_id = normalize_organization_id(raw_id)
        except ValueError as exc:
            raise AccountAdministrationError(str(exc)) from exc
        organizations = self._organizations()
        if any(
            organization_id == item.get("id") or name == item.get("name")
            for item in organizations
        ):
            raise AccountAdministrationError("机构已存在")
        organization = normalize_organization({
            "id": organization_id,
            "name": name,
            "description": str(payload.get("description") or "").strip(),
        })
        organizations.append(organization)
        levels = self._levels(organizations)
        self._persist_organizations(organizations)
        self._persist_levels(levels)
        return organization

    def create_level(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        organization_id = str(payload.get("organization_id") or "").strip()
        name = str(payload.get("name") or "").strip()
        if not organization_id or not name:
            raise AccountAdministrationError("机构和层级名称不能为空")
        organizations = self._organizations()
        if self._organization(organizations, organization_id) is None:
            raise AccountAdministrationError("机构不存在")
        levels = self._levels(organizations)
        parent = str(payload.get("parent_level_id") or "").strip()
        if parent:
            parent_level = self._level(levels, parent)
            if parent_level is None or self._level_org(parent_level) != organization_id:
                raise AccountAdministrationError("上级层级不存在或跨机构")
        base = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "level"
        level_id = f"{organization_id}__{base}"
        existing = {str(item.get("id") or "") for item in levels}
        suffix = 1
        candidate = level_id
        while candidate in existing:
            suffix += 1
            candidate = f"{level_id}_{suffix}"
        level = {
            "id": candidate,
            "organization_id": organization_id,
            "name": name,
            "parent_level_id": parent,
            "manager_username": "",
        }
        levels.append(level)
        self._persist_levels(levels)
        return level

    def update_level(self, level_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        levels = normalize_levels(self._levels(self._organizations()))
        target = self._level(levels, str(level_id or "").strip())
        if target is None:
            raise AccountAdministrationError("层级不存在")
        if "name" in payload:
            name = str(payload.get("name") or "").strip()
            if not name:
                raise AccountAdministrationError("层级名称不能为空")
            target["name"] = name
        if "parent_level_id" in payload:
            parent = str(payload.get("parent_level_id") or "").strip()
            self._validate_parent_level(levels, target["id"], parent)
            target["parent_level_id"] = parent
        if "manager_username" in payload:
            manager = str(payload.get("manager_username") or "").strip()
            if manager:
                accounts = normalize_accounts(self.store.load_accounts())
                account = next((item for item in accounts if item.get("username") == manager), None)
                if account is None or (account.get("organization_id") or "default") != self._level_org(target):
                    raise AccountAdministrationError("层级管理员不存在或不属于同一机构")
            target["manager_username"] = manager
        self._persist_levels(levels)
        return target

    def _organizations(self) -> list[dict[str, Any]]:
        organizations = [
            {
                key: self._json_value(value)
                for key, value in normalize_organization(dict(item)).items()
            }
            for item in self.store.load_organizations()
        ]
        if not any(item.get("id") == DEFAULT_ORGANIZATION_ID for item in organizations):
            organizations.insert(0, {
                "id": DEFAULT_ORGANIZATION_ID,
                "name": DEFAULT_ORGANIZATION_NAME,
                "description": "系统默认机构",
            })
        return organizations

    def _levels(self, organizations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        levels = ensure_root_levels(
            normalize_levels([dict(item) for item in self.store.load_levels()]),
            organizations,
        )
        return [
            {
                key: self._json_value(value)
                for key, value in level.items()
            }
            for level in levels
        ]

    @staticmethod
    def _organization(organizations: list[dict[str, Any]], organization_id: str) -> dict[str, Any] | None:
        return next((item for item in organizations if item.get("id") == organization_id), None)

    @staticmethod
    def _level(levels: list[dict[str, Any]], level_id: str) -> dict[str, Any] | None:
        return next((item for item in levels if item.get("id") == level_id), None)

    @staticmethod
    def _level_org(level: Mapping[str, Any]) -> str:
        return str(level.get("organization_id") or DEFAULT_ORGANIZATION_ID)

    @staticmethod
    def _validate_parent(
        parent_username: str,
        target_username: str,
        organization_id: str,
        accounts: list[dict[str, Any]],
    ) -> None:
        if not parent_username:
            return
        if parent_username == target_username:
            raise AccountAdministrationError("上级用户不能是自己")
        parent = next(
            (item for item in accounts if item.get("username") == parent_username),
            None,
        )
        if parent is None:
            raise AccountAdministrationError("上级用户不存在")
        if (parent.get("organization_id") or DEFAULT_ORGANIZATION_ID) != organization_id:
            raise AccountAdministrationError("上级用户必须属于同一机构")

    @staticmethod
    def _validate_parent_level(
        levels: list[dict[str, Any]], level_id: str, parent_level_id: str,
    ) -> None:
        if not parent_level_id:
            return
        parent = next((item for item in levels if item.get("id") == parent_level_id), None)
        target = next((item for item in levels if item.get("id") == level_id), None)
        if parent is None or target is None or AccountAdministrationService._level_org(parent) != AccountAdministrationService._level_org(target):
            raise AccountAdministrationError("上级层级不存在或跨机构")
        if parent_level_id == level_id:
            raise AccountAdministrationError("上级层级不能是自己")
        parents = {str(item.get("id") or ""): str(item.get("parent_level_id") or "") for item in levels}
        cursor = parent_level_id
        seen: set[str] = set()
        while cursor and cursor not in seen:
            if cursor == level_id:
                raise AccountAdministrationError("层级移动后会形成环路")
            seen.add(cursor)
            cursor = parents.get(cursor, "")

    @staticmethod
    def _mirror_accounts(accounts: list[dict[str, Any]]) -> None:
        try:
            save_accounts(accounts)
        except Exception:
            return

    def _persist_organizations(self, organizations: list[dict[str, Any]]) -> None:
        normalized = [normalize_organization(item) for item in organizations]
        self.store.replace_organizations(normalized)
        # PostgreSQL is committed before the local mirror is touched.  A local
        # write failure must not turn a successful central mutation into a
        # second, misleading transaction.
        try:
            save_organizations(normalized)
        except Exception:
            return

    def _persist_levels(self, levels: list[dict[str, Any]]) -> None:
        normalized = normalize_levels(levels)
        try:
            self.store.replace_levels(normalized)
        except Exception:
            raise
        try:
            save_levels(normalized)
        except Exception:
            return
