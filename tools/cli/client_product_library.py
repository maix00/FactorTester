"""Product-library and market-data HTTP client methods."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .client_base import ClientMixinBase


class ProductLibraryClientMixin(ClientMixinBase):
    """Access canonical product metadata and product-scoped data services."""

    def product_catalog(self) -> dict[str, Any]:
        return self._expect_success(
            self.session.get("/api/product-library/products")
        )

    def product_source_catalog(self) -> dict[str, Any]:
        return self._expect_success(
            self.session.get("/api/product-library/data-sources")
        )

    def product_group_catalog(self) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            "/api/product-library/product-groups",
            query={"view": "summary"},
        ))

    def create_product_group(
        self,
        *,
        name: str,
        paths: list[str],
        profile_id: str = "",
        research_refs: list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        profile = str(profile_id or "").strip()
        return self._expect_success(self.session.post(
            "/api/product-library/product-groups",
            {
                "name": name,
                "paths": paths,
                "creator_kind": "profile" if profile else "user",
                "creator_ref": f"profile:{profile}" if profile else "",
                "research_refs": list(research_refs),
            },
        ))

    def list_product_categories(self) -> dict[str, Any]:
        return self._expect_success(
            self.session.get("/api/product-library/categories")
        )

    def create_product_category(
        self, *, name: str, items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/api/product-library/categories", {"name": name, "items": items},
        ))

    def create_product_category_composite(
        self, *, category_ids: list[str] | tuple[str, ...],
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/api/product-library/categories/composite",
            {"category_ids": list(category_ids)},
        ))

    def delete_product_category(self, category_id: str) -> dict[str, Any]:
        category_id = str(category_id or "").strip()
        if not category_id:
            raise ValueError("category_id is required")
        return self._expect_success(self.session.delete(
            f"/api/product-library/categories/{quote(category_id, safe='')}"
        ))

    def product_group_subjects(
        self,
        *,
        product_group_ref: str,
        action: str = "",
        factor_refs: list[str] | tuple[str, ...] = (),
        factor_set_refs: list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        prefix = "product-group:"
        if not product_group_ref.startswith(prefix):
            raise ValueError(
                "product_group_ref must be a stable product-group reference"
            )
        group_id = product_group_ref.removeprefix(prefix).strip()
        if not group_id:
            raise ValueError("product_group_ref is empty")
        path = f"/api/product-library/product-groups/{group_id}/subjects"
        if not action:
            return self._expect_success(self.session.get(path))
        return self._expect_success(self.session.post(path, {
            "action": action,
            "factor_refs": list(factor_refs),
            "factor_set_refs": list(factor_set_refs),
        }))

    def product_fields(self, name: str) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            "/api/product-library/product-fields", query={"name": name},
        ))

    def data_availability(
        self,
        *,
        products: list[str] | tuple[str, ...],
        sources: list[str] | tuple[str, ...],
        frequencies: list[str] | tuple[str, ...] = (),
        probe: bool = False,
        expanded: bool = False,
        fields: list[str] | tuple[str, ...] = (),
        include_field_catalog: bool = False,
        include_historical_fields: bool = False,
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/api/data-availability",
            {
                "products": list(products),
                "sources": list(sources),
                "frequencies": list(frequencies),
                "probe": bool(probe),
                "expanded": bool(expanded),
                "fields": list(fields),
                "include_field_catalog": bool(include_field_catalog),
                "include_historical_fields": bool(include_historical_fields),
            },
        ))

    def data_capabilities(self) -> dict[str, Any]:
        return self._expect_success(
            self.session.get("/api/data-capabilities")
        )["catalog"]

    def data_availability_profile(self, profile_ref: str) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            f"/api/data-availability/profiles/{profile_ref}"
        ))

    def product_liquidity(
        self,
        *,
        products: list[str] | tuple[str, ...],
        source: str,
        as_of: str,
        window_days: int = 365,
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/api/product-liquidity",
            {
                "products": list(products),
                "source": str(source),
                "as_of": str(as_of),
                "window_days": int(window_days),
            },
        ))

