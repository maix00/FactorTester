"""Factor and immutable factor-set catalogs for Manager client state."""

from __future__ import annotations

import re
import sqlite3
from typing import Any


class AmbiguousFactorReferenceError(ValueError):
    """A frozen factor reference is registered by multiple visible owners."""


class ClientFactorCatalogMixin:
    """Project factor metadata from the Manager-local account mirror."""

    @staticmethod
    def _custom_source_families(
        username: str,
        owner_alias: str = "",
    ) -> list[dict[str, Any]]:
        """Keep source families visible before a parameter row is registered."""
        from server.modules.custom_factors.catalog import list_custom_factors

        families = []
        for item in list_custom_factors(username):
            alias = str(item.get("id") or item.get("name") or "").strip()
            if not alias:
                continue
            families.append({
                "factor_family_alias": alias,
                "factor_family_name": item.get("name") or alias,
                "chinese_name": item.get("chinese_name") or "",
                "description": item.get("description") or "",
                "math_expr": item.get("math_expr") or "",
                "category": item.get("category") or "",
                "categories": [item.get("category")]
                if item.get("category") else [],
                "owner_username": username,
                "owner_alias": owner_alias or username,
                "factor_kind": "custom",
                "source": "custom",
                "factor_count": 0,
                "factor_refs": [],
                # Keep parameter metadata in the family projection so a
                # nested FactorParam can render without waiting for a lazy
                # source request.
                "params": item.get("params") or [],
                "parameter_definitions": (
                    item.get("parameter_definitions")
                    or item.get("params")
                    or []
                ),
                "family_formula_fingerprint": item.get(
                    "family_formula_fingerprint"
                ) or "",
                "updated_at": item.get("updated_at") or "",
            })
        return families

    def _manifest_source_families(
        self, username: str, owner_alias: str = "",
    ) -> list[dict[str, Any]]:
        """Project factor-source families from the synced account-domain mirror.

        Source *bodies* are never shipped over the account-domain outbox; the
        mirror only carries the immutable manifest (``factor_id``,
        ``factor_name``, ``family_formula_fingerprint``, ``owner_username``,
        ``source_kind``).  A family that has synced its manifest but is missing
        its local source body would otherwise disappear from the public catalog
        listing.  The listing only needs the identity fields (family name plus
        the description column), so we render those directly from the mirror and
        leave the source body to be hydrated lazily when a single family is
        opened or a RunSpec is frozen.
        """
        rows = self._account_catalog_entities(
            username,
            entity_type="factor_source",
            include_deleted=False,
        )
        families: list[dict[str, Any]] = []
        from tools.data.sqlite.factor_family_heads import legacy_source_manifests
        for payload in legacy_source_manifests(rows, "custom", username):
            factor_id = str(payload["factor_id"]).strip()
            source_kind = "custom"
            fingerprint = str(payload.get("family_formula_fingerprint") or "").strip()
            summary = payload.get("catalog") or payload
            families.append({
                "factor_family_alias": factor_id,
                "factor_family_name": str(
                    payload.get("factor_name") or factor_id,
                ).strip() or factor_id,
                "chinese_name": summary.get("chinese_name") or "",
                "description": summary.get("description") or "",
                "math_expr": summary.get("math_expr") or "",
                "category": summary.get("category") or "",
                "categories": [summary["category"]] if summary.get("category") else [],
                "owner_username": username,
                "owner_alias": owner_alias or username,
                "factor_kind": source_kind,
                "source": source_kind,
                "factor_count": 0,
                "factor_refs": [],
                "params": summary.get("params") or [],
                "parameter_definitions": summary.get("params") or [],
                "family_formula_fingerprint": fingerprint,
                "updated_at": "",
            })
        return families

    def _merge_source_families(
        self, *family_lists: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge family rows, preferring the richest (local body) entry.

        The first list carries fully-materialized families from the local
        source table (with description/category/params); later lists are the
        manifest-only mirrors.  Same-identity rows keep the earlier, richer one.
        """
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for family_list in family_lists:
            for family in family_list:
                alias = str(
                    family.get("factor_family_alias")
                    or family.get("factor_family_name") or "",
                ).strip()
                owner = str(
                    family.get("owner_username")
                    or family.get("factor_owner_ref") or "",
                ).strip()
                if not alias:
                    continue
                key = (owner, alias)
                current = merged.get(key)
                if current is None or (not current.get("family_formula_fingerprint") and family.get("family_formula_fingerprint")):
                    merged[key] = family
        return list(merged.values())

    def _registered_factor_rows(self, principal: str, account: dict[str, Any]) -> list[dict[str, Any]]:
        local = getattr(self.account_domain_sync, "local", None)
        reader = getattr(local, "factor_catalog", None)
        if callable(reader):
            return [{**row, "owner_alias": account.get("alias") or principal,
                     "owner_organization_id": account.get("organization_id") or "",
                     "owner_organization_name": account.get("organization_name") or ""}
                    for row in reader(principal)]
        from server.manager.services.account_domain_projection import factor_rows_from_account_entities
        return factor_rows_from_account_entities(self._account_catalog_entities(
            principal, entity_type="factor_param_config", include_shared=False,
        ), principal, owner_account=account)

    def factor_detail(
        self, principal: str, factor_ref: str, *, owner_username: str = "",
    ) -> dict[str, Any] | None:
        """Resolve one registered frozen factor from the local account mirror.

        Factor refs are opaque identities and may be registered by more than
        one account. Query the exact ref index only in the caller's own and
        direct-subordinate scopes; callers that omit an owner hint get an
        explicit ambiguity error rather than an arbitrary account's row.
        """
        owner = str(principal or "").strip()
        reference = str(factor_ref or "").strip()
        requested_owner = str(owner_username or "").strip()
        if not owner:
            raise ValueError("principal is required")
        if not re.fullmatch(r"factor:v2:[A-Za-z0-9_-]{43}", reference):
            raise ValueError("因子引用无效")

        account_store = self.local_account_store
        if account_store is None:
            try:
                from server.manager.storage.local_accounts import LocalAccountStore

                account_store = LocalAccountStore()
            except (ImportError, OSError, RuntimeError, TypeError, ValueError):
                account_store = None
        from server.manager.services.subordinate_factor_library import (
            direct_subordinate_accounts,
        )

        children = direct_subordinate_accounts(owner, account_store)
        visible_owners = [owner, *(
            str(item.get("username") or "").strip()
            for item in children
            if str(item.get("username") or "").strip()
        )]
        if requested_owner:
            if requested_owner not in visible_owners:
                raise PermissionError("无权查看该用户的因子")
            visible_owners = [requested_owner]

        local = getattr(self.account_domain_sync, "local", None)
        reader = getattr(local, "factor_catalog", None)
        if not callable(reader):
            raise RuntimeError("本机因子详情索引不可用")

        matches: list[tuple[str, dict[str, Any]]] = []
        accounts_by_owner = {
            str(item.get("username") or "").strip(): item
            for item in children if str(item.get("username") or "").strip()
        }
        for candidate in visible_owners:
            try:
                rows = reader(candidate, factor_ref=reference, limit=1)
            except sqlite3.Error as exc:
                raise RuntimeError("本机因子详情索引暂时不可用") from exc
            if not rows:
                continue
            row = rows[0]
            if not isinstance(row, dict):
                continue
            row_ref = str(row.get("factor_ref") or row.get("ref") or "")
            if row_ref != reference:
                continue
            account = accounts_by_owner.get(candidate) or self._local_account(candidate)
            matches.append((candidate, {
                **row,
                "owner_username": candidate,
                "owner_alias": account.get("alias") or account.get("display_name") or candidate,
                "owner_organization_id": account.get("organization_id") or "",
                "owner_organization_name": account.get("organization_name") or "",
            }))

        if not matches:
            return None
        if len(matches) > 1:
            raise AmbiguousFactorReferenceError(
                "该因子在多个可见账户中注册，请通过所有者打开详情"
            )

        registered_owner, row = matches[0]
        source_owner_ref = str(row.get("factor_owner_ref") or row.get("owner_ref") or "").strip()
        is_public = (
            str(row.get("source") or row.get("factor_kind") or "").strip().lower() == "public"
            or source_owner_ref in {"public", "__public_jobs__"}
        )
        source_kind = "public" if is_public else "custom"
        source_owner = (
            "" if is_public else
            source_owner_ref.removeprefix("principal:") or registered_owner
        )
        family: dict[str, Any] | None = None
        metadata_available = False
        fingerprint = str(row.get("family_formula_fingerprint") or "").strip()
        family_alias = str(row.get("factor_family_alias") or "").strip()
        if fingerprint and family_alias:
            # Read the exact local source version, if present. This is a
            # single-family lookup; it deliberately does not invoke the
            # cross-server hydrator used by the source-history endpoint.
            try:
                from server.services.factor_source_catalog import FactorSourceCatalog

                source = FactorSourceCatalog().version(
                    owner,
                    source_kind,
                    family_alias,
                    fingerprint,
                    owner_username=source_owner,
                )
                metadata_available = True
                family_account = self._local_account(source_owner) if source_owner else {}
                family = {
                    "factor_family_alias": family_alias,
                    "factor_family_name": row.get("factor_family_name") or family_alias,
                    "chinese_name": source.get("chinese_name") or row.get("chinese_name") or "",
                    "description": source.get("description") or row.get("description") or "",
                    "math_expr": source.get("math_expr") or row.get("math_expr") or "",
                    "category": source.get("category") or row.get("category") or "",
                    "categories": [source.get("category") or row.get("category")]
                    if source.get("category") or row.get("category") else [],
                    "owner_username": "__public_jobs__" if is_public else source_owner,
                    "owner_alias": "公共因子库" if is_public else (
                        family_account.get("alias")
                        or family_account.get("display_name")
                        or source_owner
                    ),
                    "factor_owner_ref": source_owner_ref or registered_owner,
                    "factor_kind": source_kind,
                    "source": source_kind,
                    "family_formula_fingerprint": fingerprint,
                    "params": source.get("params") or [],
                    "parameter_definitions": source.get("params") or [],
                    "factor_count": 1,
                    "factor_refs": [reference],
                    "has_source_definition": True,
                }
            except (
                FileNotFoundError,
                PermissionError,
                OSError,
                RuntimeError,
                sqlite3.Error,
                ImportError,
                TypeError,
                ValueError,
            ):
                # Synced account mirrors intentionally omit source bytes. The
                # safe registration projection still has enough information
                # to render its frozen identity and current computed formula.
                family = None

        from server.modules.custom_factors.client_library import (
            build_client_library_projection,
        )

        projection = build_client_library_projection({
            "factors": [row],
            "families": [family] if family is not None else [],
            "errors": [],
        }, principal=owner)
        factor = next((item for item in projection.get("factors") or []
                       if item.get("factor_ref") == reference), None)
        if factor is None:
            return None
        return {
            "factor": factor,
            "family": next((item for item in projection.get("families") or []
                            if item.get("factor_family_alias") == family_alias
                            and item.get("family_formula_fingerprint") == fingerprint), None),
            "source_metadata_available": metadata_available,
        }

    def factor_library(
        self, principal: str, *, refresh: bool = False,
    ) -> dict[str, Any]:
        """Return the Manager-owned, source-free factor catalog."""
        self._refresh_account_domain_async(principal)
        from server.manager.services.account_domain_projection import (
            factor_rows_from_account_entities,
        )
        from server.modules.custom_factors.client_library import (
            build_client_library_projection,
        )
        from server.modules.custom_factors.factor_library_service import (
            build_factor_library_overview,
        )

        owner_account = self._local_account(principal)
        source_families = self._merge_source_families(
            self._custom_source_families(
                principal,
                str(owner_account.get("alias") or owner_account.get("username") or principal),
            ),
            self._manifest_source_families(principal, str(owner_account.get("alias") or "")),
        )
        if self.account_domain_sync is not None:
            mirrored = self._registered_factor_rows(principal, owner_account)
            return build_client_library_projection(
                {"factors": mirrored, "families": source_families, "errors": []}, principal=principal,
            )
        payload = build_factor_library_overview(
            principal, include_subordinates=False,
            account=owner_account,
            include_scope_catalog=False,
        )
        payload["families"] = source_families
        return build_client_library_projection(payload, principal=principal)

    def factor_library_scopes(
        self, principal: str, *, refresh: bool = False,
    ) -> dict[str, dict[str, Any]]:
        """Return the user's own and managed-user factor-family scopes.

        ``factor_library`` intentionally remains the small own-account API
        used by older callers.  This companion projection adds only accounts
        that the current account can manage; same-level peers are not treated
        as subordinates merely because they are visible in an older listing.
        """
        from server.manager.services.account_domain_projection import (
            factor_rows_from_account_entities,
        )
        from server.manager.services.subordinate_factor_library import (
            direct_subordinate_accounts,
        )
        from server.modules.custom_factors.client_library import (
            build_client_library_projection,
        )
        from server.modules.custom_factors.factor_library_service import (
            build_factor_library_overview,
        )

        mine = (
            self.factor_library(principal, refresh=True)
            if refresh else self.factor_library(principal)
        )
        account_store = self.local_account_store
        if account_store is None:
            try:
                from server.manager.storage.local_accounts import LocalAccountStore

                account_store = LocalAccountStore()
            except (ImportError, OSError, RuntimeError, TypeError, ValueError):
                account_store = None
        accounts = direct_subordinate_accounts(principal, account_store)
        subordinate_rows: list[dict[str, Any]] = []
        for account in accounts:
            owner = str(account.get("username") or "").strip()
            if not owner:
                continue
            self._refresh_account_domain_async(owner)
            subordinate_rows.extend(self._registered_factor_rows(owner, account))
        subordinate_families: list[dict[str, Any]] = []
        for account in accounts:
            owner = str(account.get("username") or "").strip()
            if not owner:
                continue
            subordinate_families.extend(self._merge_source_families(
                self._custom_source_families(
                    owner,
                    str(account.get("alias") or account.get("display_name") or owner),
                ),
                self._manifest_source_families(owner, str(account.get("alias") or account.get("display_name") or "")),
            ))
        if self.account_domain_sync is None:
            for account in accounts:
                owner = str(account.get("username") or "")
                subordinate_payload = build_factor_library_overview(
                    owner, include_subordinates=False,
                    account=account,
                    include_scope_catalog=False,
                )
                subordinate_rows.extend(subordinate_payload.get("factors") or [])
        subordinate = build_client_library_projection({
            "factors": subordinate_rows,
            "families": subordinate_families,
            "errors": [],
        }, principal=principal)
        return {
            "mine": mine,
            "subordinates": subordinate,
        }

    def factor_sets(self, principal: str, query: str = "") -> list[dict[str, Any]]:
        """Return explicitly synchronized immutable factor sets."""
        from server.modules.custom_factors.factor_set_registry import (
            factor_set_catalog,
        )

        values = factor_set_catalog(principal, query)
        if self.account_domain_sync is None:
            return values
        rows = self._account_catalog_entities(
            principal, entity_type="factor_set", include_shared=False,
        )
        self._refresh_account_domain_async(principal)
        from server.modules.custom_factors.factor_set_registry import _summary
        known = {str(item.get("target_ref") or "") for item in values}
        for row in rows:
            payload = row.get("payload") if isinstance(row, dict) else None
            if not isinstance(payload, dict) or row.get("deleted") or not payload.get("registration_active", True):
                continue
            try:
                summary = _summary(payload)
            except (KeyError, TypeError, ValueError):
                continue
            if summary["target_ref"] not in known:
                values.append(summary)
                known.add(summary["target_ref"])
        needle = query.strip().casefold()
        return [value for value in values if not needle or needle in " ".join(
            str(value.get(key) or "") for key in ("set_id", "title_zh", "description_zh", "owner_ref")
        ).casefold()]

    def factor_set_scopes(
        self, principal: str, query: str = "",
    ) -> dict[str, list[dict[str, Any]]]:
        """Return own and direct-child sets with the hierarchy boundary shared by factors."""
        from server.manager.services.subordinate_factor_library import (
            direct_subordinate_accounts,
        )

        account_store = self.local_account_store
        if account_store is None:
            try:
                from server.manager.storage.local_accounts import LocalAccountStore

                account_store = LocalAccountStore()
            except (ImportError, OSError, RuntimeError, TypeError, ValueError):
                account_store = None
        children = direct_subordinate_accounts(principal, account_store)
        subordinate: list[dict[str, Any]] = []
        for account in children:
            owner = str(account.get("username") or "").strip()
            if owner:
                subordinate.extend(self.factor_sets(owner, query))
        return {
            "mine": self.factor_sets(principal, query),
            "subordinates": subordinate,
        }

    def factor_set_detail(
        self,
        principal: str,
        target_ref: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any] | None:
        from server.modules.custom_factors.factor_set_registry import factor_set_detail

        value = factor_set_detail(
            principal, target_ref, offset=offset, limit=limit,
        )
        if value is not None or self.account_domain_sync is None:
            return value
        rows = self._account_catalog_entities(
            principal, entity_type="factor_set", include_shared=False,
        )
        payload = next(
            (
                row.get("payload") for row in rows
                if isinstance(row, dict)
                and not row.get("deleted")
                and str(row.get("entity_id") or "") == str(target_ref)
                and isinstance(row.get("payload"), dict)
            ),
            None,
        )
        if not isinstance(payload, dict):
            return None
        from server.modules.custom_factors.factor_set_registry import factor_set_page
        try:
            return factor_set_page(payload, offset=offset, limit=limit)
        except (KeyError, TypeError, ValueError):
            return None

    def factor_set_descriptor(
        self,
        principal: str, target_ref: str,
    ) -> dict[str, Any] | None:
        """Return one server-registered immutable Factor Set descriptor."""
        from server.modules.custom_factors.factor_set_registry import (
            factor_set_descriptor,
        )

        value = factor_set_descriptor(principal, target_ref)
        if value is not None or self.account_domain_sync is None:
            return value
        rows = self._account_catalog_entities(
            principal, entity_type="factor_set", include_shared=False,
        )
        payload = next(
            (
                row.get("payload") for row in rows
                if isinstance(row, dict)
                and not row.get("deleted")
                and str(row.get("entity_id") or "") == str(target_ref)
                and isinstance(row.get("payload"), dict)
            ),
            None,
        )
        if not isinstance(payload, dict):
            return None
        from tools.factors.factor_set_identity import require_frozen_factor_set
        from server.modules.custom_factors.factor_set_registry import _manifest
        try:
            frozen = require_frozen_factor_set(payload)
        except (TypeError, ValueError):
            return None
        return {"target_ref": frozen["ref"], "manifest": _manifest(payload)}
