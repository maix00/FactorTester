"""Factor and immutable factor-set catalogs for Manager client state."""

from __future__ import annotations

from typing import Any


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
                "family_formula_fingerprint": item.get(
                    "family_formula_fingerprint"
                ) or "",
                "updated_at": item.get("updated_at") or "",
            })
        return families

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
        if refresh and self.account_domain_sync is not None:
            try:
                self.account_domain_sync.reconcile_factor_catalog(
                    principal, force=True,
                )
            except (
                AttributeError, ConnectionError, OSError, RuntimeError,
                TypeError, ValueError,
            ):
                pass
        source_families = self._custom_source_families(
            principal,
            str(owner_account.get("alias") or owner_account.get("username") or principal),
        )
        if self.account_domain_sync is not None:
            mirrored = factor_rows_from_account_entities(
                self._account_catalog_entities(
                    principal,
                    entity_type="factor_param_config",
                    include_shared=False,
                ),
                principal,
                owner_account=owner_account,
            )
            try:
                # A picker must never wait for PostgreSQL or another Manager.
                # Only seed an empty source-side mirror from local factor
                # definitions; normal writes/background sync keep it fresh.
                if not mirrored:
                    self.account_domain_sync.reconcile_factor_catalog(principal)
            except (AttributeError, ConnectionError, OSError, RuntimeError, TypeError, ValueError):
                pass
            if not mirrored:
                mirrored = factor_rows_from_account_entities(
                    self._account_catalog_entities(
                        principal,
                        entity_type="factor_param_config",
                        include_shared=False,
                    ),
                    principal,
                    owner_account=owner_account,
                )
            if mirrored:
                return build_client_library_projection(
                    {
                        "factors": mirrored,
                        "families": source_families,
                        "errors": [],
                    }, principal=principal,
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
            subordinate_rows.extend(factor_rows_from_account_entities(
                self._account_catalog_entities(
                    owner,
                    entity_type="factor_param_config",
                    include_shared=False,
                ),
                owner,
                owner_account=account,
            ))
        subordinate_families: list[dict[str, Any]] = []
        for account in accounts:
            owner = str(account.get("username") or "").strip()
            if not owner:
                continue
            subordinate_families.extend(self._custom_source_families(
                owner,
                str(account.get("alias") or account.get("display_name") or owner),
            ))
        if not subordinate_rows:
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
        if not rows:
            try:
                self.account_domain_sync.reconcile_factor_catalog(principal)
            except (
                AttributeError, ConnectionError, OSError, RuntimeError,
                TypeError, ValueError,
            ):
                pass
            rows = self._account_catalog_entities(
                principal, entity_type="factor_set", include_shared=False,
            )
        known = {str(item.get("target_ref") or "") for item in values}
        for row in rows:
            payload = row.get("payload") if isinstance(row, dict) else None
            if not isinstance(payload, dict) or row.get("deleted"):
                continue
            target_ref = str(payload.get("target_ref") or "")
            if target_ref and target_ref not in known:
                values.append({
                    key: payload.get(key)
                    for key in (
                        "schema_version", "target_ref", "set_ref", "set_id",
                        "title_zh", "description_zh", "member_hash",
                        "member_count", "authority", "owner_username", "updated_at",
                    )
                })
                known.add(target_ref)
        return values

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
        members = list(payload.get("member_refs") or [])
        page = members[offset:offset + limit]
        return {
            **{key: payload.get(key) for key in (
                "schema_version", "target_ref", "set_ref", "set_id",
                "title_zh", "description_zh", "member_hash", "member_count",
                "authority", "owner_username", "updated_at",
            )},
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(page) < len(members),
            "next_offset": offset + len(page),
            "related_references": [
                {"relation": "集合成员", "kind": "factor", "target_ref": item,
                 "label": item}
                for item in page
            ],
        }

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
        return {
            "target_ref": payload.get("target_ref"),
            "manifest": {
                "schema_version": 1,
                "set_id": payload.get("set_id"),
                "set_ref": payload.get("set_ref"),
                "title_zh": payload.get("title_zh"),
                "description_zh": payload.get("description_zh") or "",
                "member_refs": list(payload.get("member_refs") or []),
                "member_hash": payload.get("member_hash"),
            },
        }
