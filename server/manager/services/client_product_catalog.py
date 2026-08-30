"""Product, category, source, and contract catalogs for client state."""

from __future__ import annotations

from typing import Any


def _catalog_exchange(product: object, name: str) -> str:
    """Read a stable exchange label without depending on a service port."""
    exchange = str(
        getattr(product, "exchange_id", "")
        or getattr(product, "exchange", "")
        or ""
    ).strip()
    if exchange:
        return exchange
    value = str(name or "")
    if "." in value:
        return value.split(".", 1)[1].split("@", 1)[0]
    parts = value.split("|")
    return parts[1] if len(parts) >= 3 else ""


class ClientProductCatalogMixin:
    """Project product metadata without selecting an execution port."""

    def _authoritative_product_groups(self, principal: str) -> list[dict[str, Any]]:
        """Read the one account-domain catalog used by lists and details."""
        from server.modules.products.product_group_store import (
            load_authoritative_product_groups,
        )

        return load_authoritative_product_groups(
            principal,
            domain_rows=self._account_catalog_entities(
                principal,
                entity_type="product_group",
                include_shared=False,
                include_deleted=True,
            ),
        )

    def product_group_summaries(self, principal: str) -> list[dict[str, Any]]:
        """Return bounded list rows without expanding product memberships."""
        groups = self._authoritative_product_groups(principal)
        summaries = []
        for group in groups:
            group_id = str(group.get("id") or "").strip()
            paths = group.get("paths") or []
            products = group.get("product_names") or []
            summaries.append({
                "id": group_id,
                "group_ref": f"product-group:{group_id}",
                "name": str(group.get("name") or group_id),
                "path_count": len(paths) if isinstance(paths, list) else 0,
                "product_count": (
                    len(products) if isinstance(products, list) else 0
                ),
                "owner_ref": str(
                    group.get("owner_ref") or f"user:{principal}"
                ),
                "creator_kind": str(group.get("creator_kind") or "user"),
                "creator_ref": str(group.get("creator_ref") or ""),
                "catalog_origin": "server",
            })
        return sorted(
            summaries,
            key=lambda item: (
                str(item.get("name") or "").casefold(),
                str(item.get("group_ref") or ""),
            ),
        )

    def product_groups(self, principal: str) -> list[dict[str, Any]]:
        """Return account groups projected against the server catalog."""
        from server.manager.domain.product_groups import (
            project_account_product_groups,
        )
        from server.modules.products.product_group_store import (
            product_group_path_bindings,
        )
        from server.services.product_catalog_projection import catalog_product_records

        profiles = self.profiles(principal)
        research = self.local_research(principal)
        groups = self._authoritative_product_groups(principal)
        for group in groups:
            if "path_bindings" not in group:
                group["path_bindings"] = product_group_path_bindings(
                    group.get("paths") or [],
                )
        projected = project_account_product_groups(
            groups=groups,
            principal=principal,
            profiles=profiles,
            research_records=research,
            product_records=[dict(item) for item in catalog_product_records()],
            origin="server",
        )
        from server.services.product_catalog_projection import (
            source_ids_by_product_path,
        )
        categories = {
            str(item.get("id") or ""): item
            for item in self.product_categories(principal)
        }
        group_paths = {
            str(path or "").strip()
            for group in projected
            for path in group.get("paths") or []
            if str(path or "").strip() and not str(path).strip().startswith("-")
        }
        path_sources = source_ids_by_product_path(group_paths)
        for group in projected:
            positive_paths = [
                str(path or "").strip()
                for path in group.get("paths") or []
                if str(path or "").strip() and not str(path).strip().startswith("-")
            ]
            group["path_sources"] = [
                {
                    "path": path,
                    "source_ids": list(path_sources.get(path, ())),
                }
                for path in positive_paths
            ]
            group["category_bindings"] = [
                categories[category_id]
                for category_id in group.get("category_ids") or []
                if category_id in categories
            ]
        return projected

    def product_group(
        self, principal: str, group_ref: str,
    ) -> dict[str, Any] | None:
        wanted = str(group_ref or "").strip()
        if not wanted:
            return None
        return next(
            (
                item for item in self.product_groups(principal)
                if str(item.get("group_ref") or "") == wanted
                or str(item.get("name") or "") == wanted
            ),
            None,
        )

    def create_product_group(
        self,
        principal: str,
        name: str,
        paths: list[str],
        category_ids: list[str] | None = None,
        *,
        creator_kind: str = "user",
        creator_ref: str = "",
        research_refs: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Create an account product group and return its catalog projection."""
        from server.modules.products.product_group_store import create_product_group

        created = create_product_group(
            principal,
            name,
            paths,
            category_ids=category_ids,
            creator_kind=creator_kind,
            creator_ref=creator_ref,
            research_refs=research_refs,
        )
        if created is None:
            return None
        return self.product_group(
            principal, f"product-group:{created['id']}",
        )

    def product_group_subjects(
        self,
        principal: str,
        group_ref: str,
    ) -> dict[str, Any] | None:
        """Read one group's factor bindings from Manager-owned state."""
        from server.modules.products.product_group_store import (
            product_group_subjects,
        )

        current = self.product_group(principal, group_ref)
        if current is None:
            return None
        return product_group_subjects(
            principal, str(current.get("group_ref") or group_ref),
        )

    def change_product_group_subjects(
        self,
        principal: str,
        group_ref: str,
        *,
        action: str,
        factor_refs: list[str],
        factor_set_refs: list[str],
    ) -> dict[str, Any] | None:
        """Change bindings after validating against the visible Manager catalog."""
        from server.modules.products.product_group_store import (
            change_product_group_subjects,
        )

        current = self.product_group(principal, group_ref)
        if current is None:
            return None
        if action == "add":
            factor_scopes = self.factor_library_scopes(principal)
            registered_factors = {
                str(item.get("factor_ref") or "")
                for scope in factor_scopes.values()
                for item in scope.get("factors") or []
                if isinstance(item, dict)
            }
            set_scopes = self.factor_set_scopes(principal)
            registered_sets = {
                str(item.get("set_ref") or item.get("target_ref") or "")
                for scope in set_scopes.values()
                for item in scope
                if isinstance(item, dict)
            }
            missing_factors = sorted(set(factor_refs) - registered_factors)
            missing_sets = sorted(set(factor_set_refs) - registered_sets)
            if missing_factors:
                raise ValueError(
                    "绑定前必须先注册因子: " + ", ".join(missing_factors)
                )
            if missing_sets:
                raise ValueError(
                    "绑定前必须先同步因子集合: " + ", ".join(missing_sets)
                )
        return change_product_group_subjects(
            principal,
            str(current.get("group_ref") or group_ref),
            action=action,
            factor_refs=factor_refs,
            factor_set_refs=factor_set_refs,
        )

    def update_product_group(
        self,
        principal: str,
        group_ref: str,
        name: str,
        paths: list[str],
        category_ids: list[str],
    ) -> dict[str, Any] | None:
        """Update one account group while keeping its stable group ID."""
        from server.modules.products.product_group_store import update_product_group

        current = self.product_group(principal, group_ref)
        if current is None:
            return None
        updated = update_product_group(
            principal,
            str(current.get("name") or ""),
            paths,
            category_ids,
            new_name=name,
        )
        if updated is None:
            return None
        return self.product_group(
            principal, str(current.get("group_ref") or group_ref),
        )

    def delete_product_group(
        self,
        principal: str,
        group_ref: str,
    ) -> bool:
        """Delete one account group resolved by stable ID or display name."""
        from server.modules.products.product_group_store import delete_product_group

        current = self.product_group(principal, group_ref)
        if current is None:
            return False
        return bool(delete_product_group(
            principal, str(current.get("name") or ""),
        ))


    def product_categories(self, principal: str = "") -> list[dict[str, Any]]:
        """Return source and account-owned product category definitions."""
        from server.modules.products.product_category_store import (
            list_product_categories,
        )
        from server.modules.shared.price_services import available_product_categories

        # Keep the old no-principal service contract for callers that only
        # need the built-in source dimensions.  An authenticated Manager
        # request gets the source definitions plus that account's categories.
        values = list_product_categories(principal) if principal else available_product_categories()
        if not principal or self.account_domain_sync is None:
            return values
        rows = self._account_catalog_entities(
            principal,
            entity_type="product_category",
            include_shared=False,
        )
        known = {str(item.get("id") or "") for item in values}
        for row in rows:
            payload = row.get("payload") if isinstance(row, dict) else None
            category_id = str(payload.get("id") or "") if isinstance(payload, dict) else ""
            if category_id and category_id not in known and not row.get("deleted"):
                value = dict(payload)
                if not value.get("is_composite") and not value.get("source_ids"):
                    from server.modules.products.product_category_store import (
                        infer_category_source_ids,
                    )
                    value["source_ids"] = infer_category_source_ids(
                        value.get("items") or [],
                    )
                value.update({
                    "owner_ref": f"user:{principal}",
                    "source_managed": False,
                })
                values.append(value)
                known.add(category_id)
        return values

    @staticmethod
    def product_sources() -> list[dict[str, Any]]:
        """Return data-source bundles registered on this server."""
        from server.services.product_catalog_projection import (
            product_source_descriptors,
        )

        return [dict(item) for item in product_source_descriptors()]

    @staticmethod
    def product_names(
        source_ids: list[str] | tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """Return products visible in this server's catalog."""
        from server.services.product_catalog_projection import filter_product_records

        return [dict(item) for item in filter_product_records(source_ids)]

    @staticmethod
    def product_fields(name: str) -> dict[str, Any] | None:
        from server.modules.shared.price_services import (
            cached_products,
            find_contract_product,
            find_product,
            product_public_fields,
        )
        from server.services.product_catalog_projection import (
            catalog_product_description,
            catalog_product_records,
        )

        wanted = str(name or "")
        record = next(
            (
                dict(item) for item in catalog_product_records()
                if item.get("name") == wanted or item.get("code") == wanted
            ),
            None,
        )
        product = (
            find_product(cached_products(), str(record["name"]))
            if record is not None else None
        )
        if product is None:
            contract = find_contract_product(wanted)
            if contract is None:
                return None
            contract_name = str(
                getattr(contract, "name", "")
                or getattr(contract, "alias", "")
                or wanted
            )
            parent = getattr(contract, "parent_product", None)
            if callable(parent):
                parent = parent()
            parent_name = str(getattr(parent, "name", "") or "")
            description = catalog_product_description(contract, contract_name)
            parent_record = next(
                (
                    item for item in catalog_product_records()
                    if item.get("name") == parent_name
                ),
                None,
            )
            return {
                "name": contract_name,
                "desc": description,
                "description": description,
                "code": contract_name,
                "exchange": "",
                "product_type": "contract",
                "product_ref": f"contract:{contract_name}",
                "product_path": "",
                "source_ids": list((parent_record or {}).get("source_ids") or []),
                "available_source_ids": list(
                    (parent_record or {}).get("available_source_ids") or []
                ),
                "parent_product": parent_name,
                "fields": product_public_fields(contract),
            }
        record["fields"] = product_public_fields(product)
        return record

    @staticmethod
    def product_contracts(
        name: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Return term-structure contracts from the installation catalog."""
        from server.services.product_market_data import contract_listing

        return contract_listing(
            name,
            start_date=start_date,
            end_date=end_date,
        )

    @staticmethod
    def product_price_series(payload: dict[str, Any]) -> dict[str, Any]:
        """Read catalog market data without selecting a backtest service."""
        from server.services.product_market_data import price_series

        return price_series(payload)

    @staticmethod
    def product_tree(
        category_id: str | list[str] | tuple[str, ...] | None = None,
        source_ids: list[str] | tuple[str, ...] | None = None,
        principal: str = "",
        *,
        checkbox_default: bool = False,
    ) -> list[dict[str, Any]]:
        """Render a Manager-owned product tree without a service port."""
        from server.modules.products.product_category_views import (
            render_product_tree,
        )

        return render_product_tree(
            category_id, principal=principal, source_ids=source_ids,
            checkbox_default=checkbox_default,
        )

    @staticmethod
    def contract_tree(
        path: str | None = None,
        category_id: str | list[str] | tuple[str, ...] | None = None,
        source_ids: list[str] | tuple[str, ...] | None = None,
        principal: str = "",
    ) -> list[dict[str, Any]]:
        """Render lazy product or contract leaves from the catalog tree."""
        return ClientProductCatalogMixin.contract_tree_page(
            path, category_id, source_ids, principal, limit=None,
        )["nodes"]

    @staticmethod
    def contract_tree_page(
        path: str | None = None,
        category_id: str | list[str] | tuple[str, ...] | None = None,
        source_ids: list[str] | tuple[str, ...] | None = None,
        principal: str = "",
        *,
        query: str = "",
        page: int = 1,
        limit: int | None = 25,
    ) -> dict[str, Any]:
        """Return one searchable, bounded page of lazy catalog leaves.

        The tree endpoint deliberately owns the paging boundary.  A browser
        or embedded client never needs to download every product merely to
        render one ``Product Lists`` folder.  ``contract_tree`` remains the
        compatibility list API for callers that do not need page metadata.
        """
        from server.modules.products.product_category_views import (
            category_products_for_path,
            tree_for_path,
        )
        from server.modules.shared.price_services import (
            available_sources_for_product,
            cached_contracts,
            contract_has_data,
        )
        from server.services.product_catalog_projection import (
            catalog_product_description,
            source_family_ids_for_member_ids,
        )
        from server.services.product_tree import find_node_by_path
        from tools.products.classifier_paths import classifier_object_path
        from tools.products.Futures import FuturesContract

        requested_page = max(1, int(page or 1))
        requested_limit = (
            10**9 if limit is None
            else min(100, max(1, int(limit or 25)))
        )
        search = str(query or "").strip().casefold()

        requested_path = str(path or "")
        node_path = requested_path
        if node_path.endswith("/_products"):
            node_path = node_path[:-10]
        tree, node_path = tree_for_path(
            node_path, category_id, principal=principal, source_ids=source_ids,
        )
        category_objects = category_products_for_path(
            node_path if "/ProductCategory/" in node_path else requested_path,
            category_id,
            principal=principal,
            source_ids=source_ids,
        )
        if category_objects is not None:
            objects = category_objects
        else:
            node = find_node_by_path(tree, node_path.split("/")) if node_path else None
            objects = (
                node.get("$OBJECTS$", [])
                if isinstance(node, dict)
                else ([] if node_path else list(cached_contracts()))
            )
        result = []
        for product in sorted(objects, key=lambda item: str(getattr(item, "name", item))):
            name = str(getattr(product, "name", product))
            is_contract = isinstance(product, FuturesContract)
            sources = available_sources_for_product(product)
            has_data = contract_has_data(name) if is_contract else bool(sources)
            description = catalog_product_description(product, name)
            value = {
                "title": name,
                "key": classifier_object_path(product),
                "checkbox": False,
                "folder": False,
                "lazy": False,
                "product_name": name,
                "product_code": str(getattr(product, "code", "") or name),
                "product_type": "contract" if is_contract else "product",
                "has_data": has_data,
                "desc": description,
                "description": description,
                "source_ids": [item["alias"] for item in sources],
                "source_family_ids": list(source_family_ids_for_member_ids(
                    item["alias"] for item in sources
                )),
                "exchange": _catalog_exchange(product, name),
                "product_path": classifier_object_path(product),
            }
            if is_contract:
                value["contract_uid"] = name
            searchable = " ".join(
                str(value.get(key) or "")
                for key in (
                    "title", "product_name", "product_code", "desc",
                    "exchange", "product_path", "source_ids",
                )
            ).casefold()
            if not search or search in searchable:
                result.append(value)
        total = len(result)
        total_pages = max(1, (total + requested_limit - 1) // requested_limit)
        offset = (requested_page - 1) * requested_limit
        return {
            "nodes": result[offset:offset + requested_limit],
            "page": requested_page,
            "limit": requested_limit,
            "total": total,
            "total_pages": total_pages,
            "has_more": requested_page < total_pages,
        }
