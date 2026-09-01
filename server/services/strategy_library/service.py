"""Application service for the persistent Strategy library."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .model import (
    inspect_source,
    normalize_entrypoint,
    normalize_text,
    normalize_visibility,
)
from .permissions import access_for, subordinate_principals
from .store import StrategyLibraryStore


class StrategyLibraryService:
    def __init__(
        self,
        db_path: str,
        *,
        account_provider: Callable[[], list[dict[str, Any]]] | None = None,
    ) -> None:
        self.store = StrategyLibraryStore(db_path)
        self.account_provider = account_provider

    def _access(
        self,
        entry: dict[str, Any],
        principal: str,
        *,
        subordinate_users: set[str] | None = None,
    ) -> dict[str, bool]:
        shares = set(self.store.shares(str(entry["strategy_ref"])))
        return access_for(
            entry,
            principal=principal,
            shared_principals=shares,
            subordinate_users=(
                subordinate_users
                if subordinate_users is not None
                else subordinate_principals(principal, self.account_provider)
            ),
        )

    def _summary(
        self,
        entry: dict[str, Any],
        principal: str,
        *,
        subordinate_users: set[str] | None = None,
    ) -> dict[str, Any]:
        revision = self.store.get_revision(str(entry["current_revision_ref"]))
        if revision is None:
            raise RuntimeError("strategy current revision is missing")
        item = dict(entry)
        item["current_revision"] = {
            key: value for key, value in revision.items()
            if key != "source_code"
        }
        item["access"] = self._access(
            entry, principal, subordinate_users=subordinate_users,
        )
        return item

    def list(
        self,
        *,
        principal: str,
        scope: str = "mine",
        page: int = 1,
        limit: int = 20,
        query: str = "",
    ) -> dict[str, Any]:
        scope = str(scope or "mine").strip().lower()
        if scope not in {"mine", "subordinates", "shared", "all"}:
            raise ValueError("strategy scope must be mine, subordinates, shared, or all")
        page = max(1, int(page))
        limit = min(100, max(1, int(limit)))
        subordinate_users = subordinate_principals(principal, self.account_provider)
        rows: list[dict[str, Any]] = []
        for entry in self.store.list_entries(query=query):
            owner = str(entry["owner_ref"])
            visibility = str(entry["visibility"])
            if scope == "mine" and owner != principal:
                continue
            if scope == "subordinates" and owner not in subordinate_users:
                continue
            if scope == "shared" and (
                owner == principal or visibility not in {"shared", "public"}
            ):
                continue
            access = self._access(
                entry, principal, subordinate_users=subordinate_users,
            )
            if not access["can_view"]:
                continue
            rows.append(self._summary(
                entry, principal, subordinate_users=subordinate_users,
            ))
        total = len(rows)
        start = (page - 1) * limit
        return {
            "success": True,
            "scope": scope,
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": max(1, (total + limit - 1) // limit),
            "items": rows[start:start + limit],
        }

    def get(self, strategy_ref: str, *, principal: str) -> dict[str, Any]:
        entry = self.store.get_entry(strategy_ref)
        if entry is None:
            raise KeyError("strategy not found")
        access = self._access(entry, principal)
        if not access["can_view"]:
            raise PermissionError("无权查看该策略")
        revision = self.store.get_revision(str(entry["current_revision_ref"]))
        if revision is None:
            raise RuntimeError("strategy current revision is missing")
        item = dict(entry)
        item["access"] = access
        item["shares"] = self.store.shares(strategy_ref) if access["can_share"] else []
        item["current_revision"] = revision
        item["revisions"] = self.store.list_revisions(strategy_ref)
        return {"success": True, "strategy": item}

    def get_revision(
        self, strategy_ref: str, revision_ref: str, *, principal: str,
    ) -> dict[str, Any]:
        entry = self.store.get_entry(strategy_ref)
        if entry is None:
            raise KeyError("strategy not found")
        if not self._access(entry, principal)["can_view"]:
            raise PermissionError("无权查看该策略版本")
        revision = self.store.get_revision(revision_ref)
        if revision is None or revision["strategy_ref"] != strategy_ref:
            raise KeyError("strategy revision not found")
        return {"success": True, "revision": revision}

    def create(self, payload: dict[str, Any], *, principal: str) -> dict[str, Any]:
        name = normalize_text(payload.get("name"), field="strategy name", limit=160)
        if not name:
            raise ValueError("strategy name is required")
        description = normalize_text(
            payload.get("description"), field="strategy description", limit=4000,
        )
        visibility = normalize_visibility(payload.get("visibility"))
        entrypoint = normalize_entrypoint(payload.get("entrypoint"))
        source = str(payload.get("source_code") or "")
        inspection = inspect_source(source, entrypoint)
        requirements = payload.get("requirements") or {}
        if not isinstance(requirements, dict):
            raise ValueError("strategy requirements must be an object")
        refs = self.store.create(
            owner_ref=principal, name=name, description=description,
            visibility=visibility, source_sha256=inspection["source_sha256"],
            source_code=source, entrypoint=entrypoint,
            hooks=inspection["hooks"], requirements=requirements,
            created_by=principal,
        )
        return self.get(refs["strategy_ref"], principal=principal)

    def update(
        self, strategy_ref: str, payload: dict[str, Any], *, principal: str,
    ) -> dict[str, Any]:
        entry = self.store.get_entry(strategy_ref)
        if entry is None:
            raise KeyError("strategy not found")
        if not self._access(entry, principal)["can_edit"]:
            raise PermissionError("无权编辑该策略")
        current = self.store.get_revision(str(entry["current_revision_ref"]))
        if current is None:
            raise RuntimeError("strategy current revision is missing")
        name = normalize_text(payload.get("name", entry["name"]), field="strategy name", limit=160)
        if not name:
            raise ValueError("strategy name is required")
        description = normalize_text(
            payload.get("description", entry["description"]),
            field="strategy description", limit=4000,
        )
        visibility = normalize_visibility(payload.get("visibility", entry["visibility"]))
        entrypoint = normalize_entrypoint(payload.get("entrypoint", current["entrypoint"]))
        source_supplied = "source_code" in payload
        source = str(payload.get("source_code") if source_supplied else current["source_code"])
        inspection = inspect_source(source, entrypoint)
        requirements = payload.get("requirements", current.get("requirements") or {})
        if not isinstance(requirements, dict):
            raise ValueError("strategy requirements must be an object")
        self.store.update_entry(
            strategy_ref, name=name, description=description, visibility=visibility,
        )
        if inspection["source_sha256"] != current["source_sha256"] \
                or entrypoint != current["entrypoint"] or requirements != current.get("requirements", {}):
            self.store.add_revision(
                strategy_ref, source_sha256=inspection["source_sha256"],
                source_code=source, entrypoint=entrypoint,
                hooks=inspection["hooks"], requirements=requirements,
                created_by=principal,
            )
        return self.get(strategy_ref, principal=principal)

    def delete(self, strategy_ref: str, *, principal: str) -> dict[str, Any]:
        entry = self.store.get_entry(strategy_ref)
        if entry is None:
            raise KeyError("strategy not found")
        if not self._access(entry, principal)["can_delete"]:
            raise PermissionError("无权删除该策略")
        if not self.store.delete(strategy_ref):
            raise KeyError("strategy not found")
        return {"success": True, "strategy_ref": strategy_ref, "status": "archived"}

    def shares(self, strategy_ref: str, *, principal: str) -> dict[str, Any]:
        entry = self.store.get_entry(strategy_ref)
        if entry is None:
            raise KeyError("strategy not found")
        if not self._access(entry, principal)["can_share"]:
            raise PermissionError("无权管理该策略共享")
        return {"success": True, "strategy_ref": strategy_ref, "shares": self.store.shares(strategy_ref)}

    def grant(self, strategy_ref: str, target: str, *, principal: str) -> dict[str, Any]:
        entry = self.store.get_entry(strategy_ref)
        if entry is None:
            raise KeyError("strategy not found")
        if not self._access(entry, principal)["can_share"]:
            raise PermissionError("无权管理该策略共享")
        target = str(target or "").strip()
        if not target or len(target) > 160:
            raise ValueError("shared principal is required")
        self.store.grant(strategy_ref, target)
        return self.shares(strategy_ref, principal=principal)

    def revoke(self, strategy_ref: str, target: str, *, principal: str) -> dict[str, Any]:
        entry = self.store.get_entry(strategy_ref)
        if entry is None:
            raise KeyError("strategy not found")
        if not self._access(entry, principal)["can_share"]:
            raise PermissionError("无权管理该策略共享")
        self.store.revoke(strategy_ref, str(target or "").strip())
        return self.shares(strategy_ref, principal=principal)
