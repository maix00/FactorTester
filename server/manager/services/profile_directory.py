"""Scoped, read-only projections for the Manager Profile directory.

The ordinary ``/api/client/profiles`` endpoint remains owner-scoped for
compatibility.  This service is the explicit directory surface used by the
Research > Profiles page.  A directory identity is always the tuple
``source_server_id + owner_ref + profile_id``; a profile id alone is not a
stable identity once more than one Manager participates in the federation.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from tools.data.account_manage import (
    direct_subordinate_accounts_for,
    get_account,
    is_super_admin_account,
    load_accounts,
)


READ_ONLY_SCOPES = {"subordinates", "servers"}
PROFILE_DIRECTORY_PRINCIPAL = "__profile_directory__"


class ProfileDirectoryError(ValueError):
    """Raised when a Profile directory request is invalid or unauthorized."""


class ProfileDirectoryService:
    """Build bounded Profile and read-only conversation projections."""

    def __init__(
        self,
        *,
        server_id: str,
        client_state: object,
        agent_profiles: object,
        federated_public_data: object | None = None,
    ) -> None:
        self.server_id = str(server_id or "").strip() or "local"
        self.client_state = client_state
        self.agent_profiles = agent_profiles
        self.federated_public_data = federated_public_data

    @staticmethod
    def _username(value: object) -> str:
        return str(value or "").strip()

    @staticmethod
    def _profile_id(value: object) -> str:
        return str(value or "").strip()

    @classmethod
    def profile_key(cls, source_server_id: object, owner_ref: object, profile_id: object) -> str:
        source = cls._username(source_server_id) or "local"
        owner = cls._username(owner_ref)
        profile = cls._profile_id(profile_id)
        if not owner or not profile:
            return ""
        return f"{source}::{owner}::{profile}"

    @staticmethod
    def _account_names() -> list[str]:
        try:
            accounts = load_accounts()
        except (OSError, RuntimeError, TypeError, ValueError):
            accounts = []
        result = {
            str(item.get("username") or "").strip()
            for item in accounts
            if isinstance(item, dict)
            and item.get("active", True)
            and str(item.get("username") or "").strip()
        }
        return sorted(result)

    @staticmethod
    def _account_label(owner: str) -> str:
        try:
            account = get_account(owner)
        except (OSError, RuntimeError, TypeError, ValueError):
            account = None
        if isinstance(account, dict):
            return str(account.get("alias") or account.get("username") or owner)
        parts = owner.split("@")
        if len(parts) == 3 and parts[1]:
            return parts[1]
        return owner

    @staticmethod
    def _profile_owner(profile: dict[str, Any], fallback: str = "") -> str:
        binding = profile.get("session_binding")
        if isinstance(binding, dict):
            value = str(binding.get("principal_ref") or "").strip()
            if value:
                return value
        for key in ("owner_ref", "principal", "username"):
            value = str(profile.get(key) or "").strip()
            if value:
                return value
        return str(fallback or "").strip()

    @staticmethod
    def _visibility(profile: dict[str, Any]) -> str:
        value = str(
            profile.get("visibility")
            or profile.get("profile_visibility")
            or "private"
        ).strip().lower()
        return value if value in {"private", "public", "authorized"} else "private"

    @staticmethod
    def _authorized_users(profile: dict[str, Any]) -> set[str]:
        values = profile.get("authorized_users")
        if not isinstance(values, list):
            return set()
        return {str(item or "").strip() for item in values if str(item or "").strip()}

    @classmethod
    def visible_to(cls, profile: dict[str, Any], viewer: str, *, admin: bool = False) -> bool:
        owner = cls._profile_owner(profile)
        if owner == viewer or admin:
            return True
        visibility = cls._visibility(profile)
        return visibility == "public" or (
            visibility == "authorized" and viewer in cls._authorized_users(profile)
        )

    @staticmethod
    def _runtime(profile: dict[str, Any], source_server_id: str) -> dict[str, Any]:
        raw = profile.get("runtime")
        runtime = dict(raw) if isinstance(raw, dict) else {}
        runtime_kind = str(
            runtime.get("runtime_kind")
            or profile.get("runtime_kind")
            or "client"
        ).strip()
        executor = str(
            runtime.get("executor_id")
            or profile.get("execution_server_id")
            or profile.get("execution_device_id")
            or ""
        ).strip()
        if runtime_kind == "server" and not executor:
            server = profile.get("server")
            if isinstance(server, dict):
                executor = str(server.get("server_id") or "").strip()
        return {
            "runtime_kind": runtime_kind if runtime_kind in {"server", "client"} else "client",
            "executor_id": executor,
            "configured": bool(runtime.get("configured", executor)),
            "server_id": source_server_id if runtime_kind == "server" else "",
        }

    @staticmethod
    def _claim(profile: dict[str, Any]) -> dict[str, Any] | None:
        raw = profile.get("active_claim")
        if not isinstance(raw, dict):
            return None
        # Provider ids and claim ids are not needed by a directory viewer.
        return {
            key: raw.get(key)
            for key in (
                "runtime_kind", "executor_id", "agent_id", "status",
                "claimed_at", "last_heartbeat_at",
            )
            if key in raw
        }

    def _local_profiles(self, owners: Iterable[str]) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for owner in owners:
            try:
                rows = self.client_state.profiles(owner, include_local_paths=False)
            except TypeError:
                rows = self.client_state.profiles(owner)
            for row in rows or []:
                if isinstance(row, dict):
                    values.append({**row, "source_server_id": self.server_id})
        return values

    def _profiles(self, owners: list[str]) -> list[dict[str, Any]]:
        federated = self.federated_public_data
        if federated is not None:
            reader = getattr(federated, "profile_directory", None)
            if callable(reader):
                try:
                    return [
                        dict(item) for item in reader(owners)
                        if isinstance(item, dict)
                    ]
                except (ConnectionError, OSError, RuntimeError, TypeError, ValueError):
                    # A peer outage must not hide locally mirrored Profiles.
                    pass
        return self._local_profiles(owners)

    def _enrich_local(self, profile: dict[str, Any], owner: str, source: str) -> dict[str, Any]:
        if source != self.server_id:
            return profile
        try:
            enriched = self.agent_profiles.enrich(owner, [profile])
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            enriched = []
        return dict(enriched[0]) if enriched else profile

    def _project(
        self,
        profile: dict[str, Any],
        *,
        current: str,
        scope: str,
        requested_owner: str = "",
    ) -> dict[str, Any] | None:
        owner = self._profile_owner(profile, requested_owner)
        profile_id = self._profile_id(profile.get("profile_id"))
        source = self._username(profile.get("source_server_id")) or self.server_id
        if not owner or not profile_id:
            return None
        profile = self._enrich_local(profile, owner, source)
        runtime = self._runtime(profile, source)
        conversation_sharing = bool(profile.get("conversation_sharing", False))
        if source == self.server_id:
            try:
                conversation_sharing = self.agent_profiles.conversation_sharing(
                    owner, profile_id,
                )
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                pass
        profile_for_access = {
            **profile,
            "conversation_sharing": conversation_sharing,
        }
        claim = self._claim(profile)
        conversation_count = profile.get("conversation_count")
        if conversation_count is None and source == self.server_id:
            try:
                conversation_count = len(self.agent_profiles.conversations(owner, profile_id))
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                conversation_count = 0
        # The server directory is a catalog, not an automatic lock on the
        # current user's local Profile.  Only another owner or another
        # Manager is read-only; the subordinate scope is already owner-only.
        read_only = owner != current or source != self.server_id
        capabilities = {
            "view": True,
            "edit": not read_only and owner == current,
            "bind": not read_only and owner == current and source == self.server_id,
            "view_conversations": self.can_view_conversations(
                current, owner, profile_for_access, source_server_id=source,
            ),
            "read_only_conversations": read_only,
        }
        return {
            "profile_key": self.profile_key(source, owner, profile_id),
            "owner_ref": owner,
            "owner_alias": self._account_label(owner),
            "profile_id": profile_id,
            "display_name": str(profile.get("display_name") or profile_id),
            "source_server_id": source,
            "execution_server_id": runtime.get("executor_id", "") if runtime.get("runtime_kind") == "server" else "",
            "runtime_kind": runtime.get("runtime_kind", "client"),
            "runtime": runtime,
            "binding_status": "bound" if runtime.get("configured") else "unbound",
            "agent_status": "claimed" if claim else "unclaimed",
            "agent_runtime_status": str(claim.get("status") or "") if claim else "",
            "agent_id": str(claim.get("agent_id") or "") if claim else "",
            "conversation_count": int(conversation_count or 0),
            "updated_at": profile.get("updated_at") or profile.get("synced_at") or 0,
            "visibility": self._visibility(profile),
            "conversation_sharing": conversation_sharing,
            "read_only": read_only,
            "capabilities": capabilities,
        }

    def _owners_for_scope(self, current: str, scope: str) -> tuple[list[str], bool]:
        if scope == "mine":
            return [current], False
        if scope == "subordinates":
            return [
                str(item.get("username") or "").strip()
                for item in direct_subordinate_accounts_for(current)
                if str(item.get("username") or "").strip()
            ], True
        if scope == "servers":
            return self._account_names() or [current], True
        raise ProfileDirectoryError("unsupported Profile directory scope")

    def directory(
        self,
        current: str,
        *,
        scope: str = "mine",
        query: str = "",
        page: int = 1,
        page_size: int = 20,
        server_id: str = "",
        binding: str = "",
        agent: str = "",
    ) -> dict[str, Any]:
        viewer = self._username(current)
        if not viewer:
            raise ProfileDirectoryError("authenticated principal is required")
        scope = str(scope or "mine").strip().lower()
        owners, read_only_scope = self._owners_for_scope(viewer, scope)
        try:
            account = get_account(viewer)
        except (OSError, RuntimeError, TypeError, ValueError):
            account = None
        admin = is_super_admin_account(account)
        raw_profiles = self._profiles(owners)
        projected: dict[str, dict[str, Any]] = {}
        for raw in raw_profiles:
            owner = self._profile_owner(raw)
            if scope == "subordinates" and owner not in set(owners):
                continue
            if scope == "servers" and not admin and not self.visible_to(raw, viewer):
                continue
            value = self._project(
                raw, current=viewer, scope=scope,
                requested_owner=owner,
            )
            if value is None:
                continue
            if server_id and value["source_server_id"] != server_id:
                continue
            if binding and value["binding_status"] != binding:
                continue
            if agent and value["agent_status"] != agent:
                continue
            key = str(value["profile_key"])
            projected[key] = value
        values = list(projected.values())
        needle = str(query or "").strip().casefold()
        if needle:
            values = [
                item for item in values
                if needle in " ".join(
                    str(item.get(key) or "")
                    for key in (
                        "owner_alias", "owner_ref", "profile_id",
                        "display_name", "source_server_id", "agent_id",
                    )
                ).casefold()
            ]
        values.sort(key=lambda item: (
            str(item.get("owner_alias") or "").casefold(),
            str(item.get("display_name") or "").casefold(),
            str(item.get("profile_key") or ""),
        ))
        page = max(1, int(page or 1))
        page_size = max(1, min(100, int(page_size or 20)))
        start = (page - 1) * page_size
        items = values[start:start + page_size]
        return {
            "success": True,
            "scope": scope,
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": len(values),
            "has_more": start + page_size < len(values),
            "read_only": read_only_scope,
            "server_id": self.server_id,
        }

    def detail(self, current: str, profile_key: str, *, scope: str = "servers") -> dict[str, Any]:
        item, _, _ = self._source_profile(current, profile_key, scope=scope)
        return {"success": True, "profile": item, "read_only": bool(item.get("read_only"))}

    def can_view_conversations(
        self,
        viewer: str,
        owner: str,
        profile: dict[str, Any] | None = None,
        *,
        source_server_id: str = "",
    ) -> bool:
        viewer = self._username(viewer)
        owner = self._username(owner)
        if not viewer or not owner:
            return False
        if viewer == owner:
            return True
        try:
            account = get_account(viewer)
        except (OSError, RuntimeError, TypeError, ValueError):
            account = None
        if is_super_admin_account(account):
            return True
        if owner not in {
            str(item.get("username") or "").strip()
            for item in direct_subordinate_accounts_for(viewer)
        }:
            return False
        return bool(profile and profile.get("conversation_sharing"))

    def _source_profile(
        self,
        viewer: str,
        profile_key: str,
        *,
        scope: str = "servers",
    ) -> tuple[dict[str, Any], str, str] | None:
        value = str(profile_key or "").strip()
        parts = value.split("::", 2)
        if len(parts) != 3:
            raise ProfileDirectoryError("profile_key is invalid")
        source, owner, profile_id = parts
        directory = self.directory(
            viewer,
            scope=scope,
            query=profile_id,
            page_size=100,
            server_id=source,
        )
        for item in directory["items"]:
            if item.get("profile_key") == value:
                return item, owner, profile_id
        raise ProfileDirectoryError("Profile is not visible to current account")

    def conversations(self, viewer: str, profile_key: str, *, scope: str = "servers") -> list[dict[str, Any]]:
        item, owner, profile_id = self._source_profile(viewer, profile_key, scope=scope)
        if not item["capabilities"].get("view_conversations"):
            raise PermissionError("Profile conversations are not shared with this account")
        source = str(item.get("source_server_id") or self.server_id)
        if source == self.server_id:
            rows = self.agent_profiles.conversations(owner, profile_id)
        else:
            reader = getattr(self.federated_public_data, "profile_conversations", None)
            if not callable(reader):
                return []
            rows = reader(source, viewer, owner, profile_id)
        return [self._public_conversation(row, read_only=item["read_only"]) for row in rows]

    def conversation_items(
        self,
        viewer: str,
        profile_key: str,
        conversation_id: str,
        *,
        scope: str = "servers",
    ) -> list[dict[str, Any]]:
        item, owner, profile_id = self._source_profile(viewer, profile_key, scope=scope)
        if not item["capabilities"].get("view_conversations"):
            raise PermissionError("Profile conversations are not shared with this account")
        source = str(item.get("source_server_id") or self.server_id)
        if source == self.server_id:
            rows = self.agent_profiles.conversation_items(owner, profile_id, conversation_id)
        else:
            reader = getattr(self.federated_public_data, "profile_conversation_items", None)
            if not callable(reader):
                return []
            rows = reader(source, viewer, owner, profile_id, conversation_id)
        return [dict(row) for row in rows if isinstance(row, dict)]

    @staticmethod
    def _public_conversation(value: dict[str, Any], *, read_only: bool) -> dict[str, Any]:
        return {
            key: value.get(key)
            for key in (
                "conversation_id", "profile_id", "title", "preview",
                "created_at", "updated_at", "active",
            )
            if key in value
        } | {"read_only": bool(read_only)}


__all__ = [
    "PROFILE_DIRECTORY_PRINCIPAL",
    "ProfileDirectoryError",
    "ProfileDirectoryService",
]
