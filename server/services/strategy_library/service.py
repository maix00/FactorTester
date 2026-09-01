"""Application service for the persistent Strategy library."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from server.services.strategy_source_inspection import inspect_source, normalize_entrypoint

from .model import normalize_text, normalize_visibility
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
        explicitly_shared: bool | None = None,
    ) -> dict[str, bool]:
        shares = (
            {principal} if explicitly_shared
            else set() if explicitly_shared is not None
            else set(self.store.shares(str(entry["strategy_ref"])))
        )
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
        revision: dict[str, Any] | None = None,
        explicitly_shared: bool | None = None,
    ) -> dict[str, Any]:
        revision = revision or self.store.get_revision(str(entry["current_revision_ref"]))
        if revision is None:
            raise RuntimeError("strategy current revision is missing")
        item = dict(entry)
        item["current_revision"] = {
            key: value for key, value in revision.items()
            if key != "source_code"
        }
        item["access"] = self._access(
            entry, principal, subordinate_users=subordinate_users,
            explicitly_shared=explicitly_shared,
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
        visible, total = self.store.list_visible_entries(
            principal=principal, scope=scope,
            subordinate_users=subordinate_users, query=query,
            page=page, limit=limit,
        )
        rows = [self._summary(
            value["entry"], principal,
            subordinate_users=subordinate_users,
            revision=value["revision"],
            explicitly_shared=value["explicitly_shared"],
        ) for value in visible]
        return {
            "success": True,
            "scope": scope,
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": max(1, (total + limit - 1) // limit),
            "items": rows,
        }

    def get(
        self, strategy_ref: str, *, principal: str,
        include_source: bool = True,
    ) -> dict[str, Any]:
        entry = self.store.get_entry(strategy_ref)
        if entry is None:
            raise KeyError("strategy not found")
        access = self._access(entry, principal)
        if not access["can_view"]:
            raise PermissionError("无权查看该策略")
        revision = self.store.get_revision(
            str(entry["current_revision_ref"]), include_source=include_source,
        )
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
        include_source: bool = True,
    ) -> dict[str, Any]:
        entry = self.store.get_entry(strategy_ref)
        if entry is None:
            raise KeyError("strategy not found")
        if not self._access(entry, principal)["can_view"]:
            raise PermissionError("无权查看该策略版本")
        revision = self.store.get_revision(
            revision_ref, include_source=include_source,
        )
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
            hooks=inspection.get("effective_hooks", inspection["hooks"]),
            requirements=requirements,
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
        source_definition_changed = source_supplied or "entrypoint" in payload
        inspection = inspect_source(source, entrypoint) if source_definition_changed else {
            "source_sha256": current["source_sha256"],
            "hooks": current.get("hooks") or [],
            "effective_hooks": current.get("hooks") or [],
        }
        requirements = payload.get("requirements", current.get("requirements") or {})
        if not isinstance(requirements, dict):
            raise ValueError("strategy requirements must be an object")
        revision = None
        if inspection["source_sha256"] != current["source_sha256"] \
                or entrypoint != current["entrypoint"] \
                or requirements != current.get("requirements", {}):
            revision = {
                "source_sha256": inspection["source_sha256"],
                "source_code": source,
                "entrypoint": entrypoint,
                "hooks": inspection.get("effective_hooks", inspection["hooks"]),
                "requirements": requirements,
                "created_by": principal,
            }
        self.store.update_entry_with_revision(
            strategy_ref,
            name=name,
            description=description,
            visibility=visibility,
            expected_revision_ref=str(current["revision_ref"]),
            revision=revision,
        )
        return self.get(
            strategy_ref,
            principal=principal,
            include_source=source_definition_changed,
        )

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
