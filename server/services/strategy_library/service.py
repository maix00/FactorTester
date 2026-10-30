"""Application service for the persistent Strategy library."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from server.services.strategy_source_inspection import inspect_source, normalize_entrypoint
from server.services.factor_strategy_templates import normalize_factor_bindings

from .model import normalize_text, normalize_visibility
from .permissions import access_for, access_many, subordinate_principals
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
        self.source_loader = None

    def _read_revision(self, revision_ref, *, principal, include_source=True):
        revision = self.store.get_revision(revision_ref, include_source=include_source)
        if include_source and revision is not None and not revision.get('source_code'):
            if self.source_loader is None:
                raise RuntimeError('strategy revision source is unavailable')
            revision = self.source_loader(revision_ref, principal=principal)
        return revision

    def _access(
        self,
        entry: dict[str, Any],
        principal: str,
        *,
        subordinate_users: set[str] | None = None,
        explicitly_shared: bool | None = None,
    ) -> dict[str, bool]:
        shares = set()
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
        access: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        revision = revision or self.store.get_revision(
            str(entry["current_revision_ref"]), include_source=False,
        )
        if revision is None:
            raise RuntimeError("strategy current revision is missing")
        item = dict(entry)
        item["library_scope"] = "user_custom"
        item["library_kind"] = "nautilus_strategy_source"
        item["current_revision"] = {
            key: value for key, value in revision.items()
            if key != "source_code"
        }
        item["access"] = access if access is not None else self._access(
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
        rows, total, scan_page = [], 0, 1
        lower, upper = (page - 1) * limit, page * limit
        # Page metadata, never source. Authorize before counting/pagination;
        # a denied local share must not leak a row or inflate the visible total.
        while True:
            candidates, candidate_total = self.store.list_visible_entries(
                principal=principal, scope=scope,
                subordinate_users=subordinate_users, query=query,
                page=scan_page, limit=100,
            )
            access = access_many([v["entry"] for v in candidates],
                                 principal=principal, subordinate_users=subordinate_users)
            for value in candidates:
                decision = access[str(value["entry"]["strategy_ref"])]
                if not decision["can_view"]:
                    continue
                if lower <= total < upper:
                    rows.append(self._summary(
                        value["entry"], principal, subordinate_users=subordinate_users,
                        revision=value["revision"], access=decision,
                    ))
                total += 1
            if not candidates or scan_page * 100 >= candidate_total:
                break
            scan_page += 1
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
        include_source: bool = False,
    ) -> dict[str, Any]:
        entry = self.store.get_entry(strategy_ref)
        if entry is None:
            raise KeyError("strategy not found")
        access = self._access(entry, principal)
        if not access["can_view"]:
            raise PermissionError("无权查看该策略")
        revision = self._read_revision(
            str(entry["current_revision_ref"]), principal=principal, include_source=include_source,
        )
        if revision is None:
            raise RuntimeError("strategy current revision is missing")
        item = dict(entry)
        item["library_scope"] = "user_custom"
        item["library_kind"] = "nautilus_strategy_source"
        item["access"] = access
        item["shares"] = []
        item["permissions_managed_by"] = "keycloak"
        item["current_revision"] = revision
        item["revisions"] = self.store.list_revisions(strategy_ref)
        return {"success": True, "strategy": item}

    def get_revision(
        self, strategy_ref: str, revision_ref: str, *, principal: str,
        include_source: bool = False,
    ) -> dict[str, Any]:
        entry = self.store.get_entry(strategy_ref)
        if entry is None:
            raise KeyError("strategy not found")
        if not self._access(entry, principal)["can_view"]:
            raise PermissionError("无权查看该策略版本")
        revision = self._read_revision(
            revision_ref, principal=principal, include_source=include_source,
        )
        if revision is None or revision["strategy_ref"] != strategy_ref:
            raise KeyError("strategy revision not found")
        return {"success": True, "revision": revision}

    def validate_revision(
        self,
        strategy_ref: str,
        revision_ref: str,
        *,
        principal: str,
        source_sha256: str = "",
    ) -> dict[str, Any]:
        """Validate an executable revision without transferring its source."""
        revision = self.get_revision(
            strategy_ref,
            revision_ref,
            principal=principal,
            include_source=False,
        )["revision"]
        requested_hash = str(source_sha256 or "").strip()
        if requested_hash and requested_hash != revision["source_sha256"]:
            raise ValueError("library strategy revision source hash mismatch")
        return revision

    def create(self, payload: dict[str, Any], *, principal: str) -> dict[str, Any]:
        from server.identity.keycloak_authorization import (
            keycloak_request_identity, ensure_keycloak_resource,
        )
        identity = keycloak_request_identity()
        if identity is None or identity.username != principal:
            raise PermissionError("Strategy creation requires a verified Keycloak identity")
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
        requirements = _normalize_requirements(requirements)
        refs = self.store.create(
            owner_ref=principal, name=name, description=description,
            visibility=visibility, source_sha256=inspection["source_sha256"],
            source_code=source, entrypoint=entrypoint,
            hooks=inspection.get("effective_hooks", inspection["hooks"]),
            requirements=requirements,
            created_by=principal,
        )
        try:
            ensure_keycloak_resource(
                resource_type="strategy", resource_ref=refs["strategy_ref"],
                owner_subject=identity.subject,
            )
        except Exception:
            # Preserve the revision for audit, but do not expose a half-created
            # active strategy when its authoritative permission could not bind.
            self.store.delete(refs["strategy_ref"])
            raise
        return self.get(
            refs["strategy_ref"], principal=principal, include_source=False,
        )

    def update(
        self, strategy_ref: str, payload: dict[str, Any], *, principal: str,
    ) -> dict[str, Any]:
        entry = self.store.get_entry(strategy_ref)
        if entry is None:
            raise KeyError("strategy not found")
        if not self._access(entry, principal)["can_edit"]:
            raise PermissionError("无权编辑该策略")
        current = self._read_revision(str(entry["current_revision_ref"]), principal=principal)
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
        requirements = _normalize_requirements(requirements)
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
        return self.get(strategy_ref, principal=principal, include_source=False)

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
        return {"success": True, "strategy_ref": strategy_ref, "shares": [],
                "managed_externally": True, "identity_provider": "keycloak"}

    def grant(self, strategy_ref: str, target: str, *, principal: str) -> dict[str, Any]:
        raise PermissionError("Strategy grants are managed in Keycloak")

    def revoke(self, strategy_ref: str, target: str, *, principal: str) -> dict[str, Any]:
        raise PermissionError("Strategy grants are managed in Keycloak")


def _normalize_requirements(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    if "factor_bindings" in result:
        result["factor_bindings"] = normalize_factor_bindings(
            result["factor_bindings"],
            field="strategy requirements factor_bindings",
        )
    return result
