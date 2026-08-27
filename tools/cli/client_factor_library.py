"""Navigation, factor library, and factor workspace HTTP client methods."""

from __future__ import annotations

from typing import Any

from .client_base import ClientMixinBase


class FactorLibraryClientMixin(ClientMixinBase):
    def product_catalog(self) -> dict[str, Any]:
        """Read the same server product catalog used by Web and Swift."""
        return self._expect_success(self.session.get("/api/catalog/products"))

    def product_source_catalog(self) -> dict[str, Any]:
        """Read the same server data-source catalog used by Web and Swift."""
        return self._expect_success(self.session.get("/api/catalog/sources"))

    def product_group_catalog(self) -> dict[str, Any]:
        """Read bounded product-group rows from the Manager-owned catalog."""
        return self._expect_success(
            self.session.get(
                "/api/catalog/product-groups", query={"view": "summary"},
            )
        )

    def list_modules(self, parent: str | None = None) -> list[dict[str, Any]]:
        if parent is None:
            return self.home_modules()
        if parent == "products":
            return [
                {
                    "key": "products/info",
                    "label": "产品后端信息",
                    "kind": "module",
                    "has_children": False,
                },
                {
                    "key": "products/product-groups",
                    "label": "产品组库",
                    "kind": "module",
                    "has_children": False,
                },
                {
                    "key": "products/categories",
                    "label": "产品分类库",
                    "kind": "module",
                    "has_children": False,
                },
                {
                    "key": "products/availability",
                    "label": "数据可用性",
                    "kind": "module",
                    "has_children": False,
                },
                {
                    "key": "products/liquidity",
                    "label": "逐产品流动性证据",
                    "kind": "module",
                    "has_children": False,
                },
            ]
        if parent == "custom_factors":
            return [
                {
                    "key": "custom_factors/factor-library",
                    "label": "因子库",
                    "kind": "module",
                    "has_children": False,
                },
                {
                    "key": "custom_factors/workspace",
                    "label": "本地 factor workspace",
                    "kind": "module",
                    "has_children": False,
                },
                {
                    "key": "custom_factors/operators",
                    "label": "FactorExpr 算子",
                    "kind": "module",
                    "has_children": False,
                },
            ]
        query = {"parent": parent} if parent else None
        data = self._expect_success(
            self.session.get("/api/testers/modules", query=query)
        )
        if parent and data.get("parent") != parent:
            raise RuntimeError(
                "服务端 /api/testers/modules 还不是分层导航版本，"
                "请更新并重启服务端后再访问下一层。"
            )
        modules = data.get("modules")
        if not isinstance(modules, list):
            raise ValueError("服务器 modules 响应格式错误")
        return modules

    def home_modules(self) -> list[dict[str, Any]]:
        data = self.session.get("/static/config/modules.json")
        modules = data.get("modules")
        if not isinstance(modules, list):
            raise ValueError("服务器 home modules 响应格式错误")
        return [
            {
                "key": str(module.get("id") or ""),
                "label": module.get("title") or module.get("id"),
                "kind": "module",
                "path": module.get("path"),
                "description": module.get("desc"),
                "has_children": True,
            }
            for module in modules
            if module.get("id")
        ]

    def manifest(self, application: str) -> dict[str, Any]:
        return self._expect_success(
            self.session.get(f"/api/backtest/settings/{application}")
        )

    def tab_manifest(
        self,
        application: str,
        tab_key: str,
    ) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            f"/api/backtest/settings/{application}/tabs/{tab_key}"
        ))

    def list_candidates(
        self,
        kind: str,
        **params: Any,
    ) -> list[dict[str, Any]]:
        if kind in {"factor", "factor_candidates", "factor_selections"}:
            data = self._expect_success(
                self.session.get("/api/factor-library-overview", query=params)
            )
            for key in ("factors", "items", "configs", "families"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
            return []
        raise ValueError(f"CLI 暂不支持候选列表类型: {kind}")

    def add_candidate(
        self,
        kind: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if kind in {"factor", "factor_candidates", "factor_selections"}:
            return self._expect_success(
                self.session.post("/add_factor_by_params", payload)
            )
        raise ValueError(f"CLI 暂不支持新增候选类型: {kind}")

    def create_custom_factor(
        self,
        *,
        source_code: str,
        chinese_name: str = "",
        description: str = "",
        category: str = "自编",
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/custom-factors/api/create",
            {
                "source_code": source_code,
                "chinese_name": chinese_name,
                "description": description,
                "category": category,
            },
        ))

    def factor_expr_operators(self) -> dict[str, Any]:
        return self._expect_success(
            self.session.get("/custom-factors/api/visual-operators")
        )

    def custom_factor_catalog(
        self,
        *,
        include_subordinates: bool = False,
    ) -> dict[str, Any]:
        query = {"include_subordinates": "1"} if include_subordinates else None
        return self._expect_success(
            self.session.get("/custom-factors/api/list", query=query)
        )

    def validate_factor_expr(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.post("/custom-factors/api/validate", payload)
        )

    def create_product_group(
        self,
        *,
        name: str,
        paths: list[str],
        profile_id: str = "",
        research_refs: list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        profile = str(profile_id or "").strip()
        return self._expect_success(
            self.session.post(
                "/api/catalog/product-groups",
                {
                    "name": name,
                    "paths": paths,
                    "creator_kind": "profile" if profile else "user",
                    "creator_ref": f"profile:{profile}" if profile else "",
                    "research_refs": list(research_refs),
                },
            )
        )

    def list_product_categories(self) -> dict[str, Any]:
        """List source and current-user product categories."""
        return self._expect_success(self.session.get("/api/catalog/categories"))

    def create_product_category(
        self,
        *,
        name: str,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create one user-owned product category."""
        return self._expect_success(self.session.post(
            "/api/catalog/categories",
            {"name": name, "items": items},
        ))

    def create_product_category_composite(
        self,
        *,
        category_ids: list[str] | tuple[str, ...],
    ) -> dict[str, Any]:
        """Create one registered product-category composition."""
        return self._expect_success(self.session.post(
            "/api/catalog/categories/composite",
            {"category_ids": list(category_ids)},
        ))

    def delete_product_category(self, category_id: str) -> dict[str, Any]:
        """Delete one user-owned product category."""
        category_id = str(category_id or "").strip()
        if not category_id:
            raise ValueError("category_id is required")
        from urllib.parse import quote

        return self._expect_success(self.session.delete(
            f"/api/catalog/categories/{quote(category_id, safe='')}"
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
            raise ValueError("product_group_ref must be a stable product-group reference")
        group_id = product_group_ref.removeprefix(prefix).strip()
        if not group_id:
            raise ValueError("product_group_ref is empty")
        path = f"/api/catalog/product-groups/{group_id}/subjects"
        if not action:
            return self._expect_success(self.session.get(path))
        return self._expect_success(self.session.post(path, {
            "action": action,
            "factor_refs": list(factor_refs),
            "factor_set_refs": list(factor_set_refs),
        }))

    def list_registered_factor_sets(self, *, query: str = "") -> dict[str, Any]:
        params = {"query": query} if query else None
        return self._expect_success(self.session.get(
            "/custom-factors/api/client/factor-sets", query=params,
        ))

    def register_factor_set(self, descriptor: dict[str, Any]) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/custom-factors/api/client/factor-sets",
            {"descriptor": descriptor},
        ))

    def unregister_factor_set(self, target_ref: str) -> dict[str, Any]:
        return self._expect_success(self.session.delete(
            "/custom-factors/api/client/factor-sets",
            query={"target_ref": target_ref},
        ))

    def product_fields(self, name: str) -> dict[str, Any]:
        return self._expect_success(
            self.session.get("/api/product_fields", query={"name": name})
        )

    def validate_report_reference(
        self, *, kind: str, target_ref: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            "/api/report-references/validate",
            query={"kind": kind, "target_ref": target_ref},
        ))
        reference = data.get("reference")
        if not isinstance(reference, dict):
            raise ValueError("服务器 report reference 响应格式错误")
        return reference

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
        """Inspect only the explicitly requested market-data scope."""
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
        """Read declared sources and materialized coverage snapshots."""
        return self._expect_success(
            self.session.get("/api/data-capabilities")
        )["catalog"]

    def data_availability_profile(self, profile_ref: str) -> dict[str, Any]:
        """Read one frozen profile without inspecting its data sources."""
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
        """Compute one batch of point-in-time DAY1 volume evidence."""
        return self._expect_success(self.session.post(
            "/api/product-liquidity",
            {
                "products": list(products),
                "source": str(source),
                "as_of": str(as_of),
                "window_days": int(window_days),
            },
        ))

    def factor_library_overview(
        self,
        *,
        factor_family: str = "",
        product_group: str = "",
        include_subordinates: bool = False,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {}
        if factor_family:
            query["factor_family_alias"] = factor_family
        if product_group:
            query["product_group"] = product_group
        if include_subordinates:
            query["include_subordinates"] = "1"
        return self._expect_success(self.session.get(
            "/custom-factors/api/factor-library-overview",
            query=query or None,
        ))

    def factor_catalog(self) -> dict[str, Any]:
        """Read the Manager-owned factor catalog used by Web and Swift."""
        return self._expect_success(self.session.get("/api/catalog/factors"))

    def factor_set_catalog(self, *, query: str = "") -> dict[str, Any]:
        """Read scoped immutable Factor Sets from the Manager catalog."""
        params = {"query": query} if query else None
        return self._expect_success(self.session.get(
            "/api/catalog/factor-sets", query=params,
        ))

    def factor_library_source_projection(
        self,
        owner_ref: str,
    ) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            f"/custom-factors/api/client/factor-library-sources/"
            f"{owner_ref}/projection",
        ))

    def factor_library_sources(self) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            "/custom-factors/api/client/factor-library-sources"
        ))

    def factor_library_configs(
        self,
        factor_family: str,
        *,
        product_group: str = "",
    ) -> dict[str, Any]:
        query = {"product_group": product_group} if product_group else None
        return self._expect_success(self.session.get(
            f"/custom-factors/api/factor-library-configs/{factor_family}",
            query=query,
        ))

    def save_factor_library_config(
        self,
        factor_family: str,
        *,
        product_group: str,
        params_list: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "product_group": product_group,
            "params_list": params_list,
        }
        if metadata:
            payload["metadata"] = metadata
        return self._expect_success(self.session.put(
            f"/custom-factors/api/factor-library-configs/{factor_family}",
            payload,
        ))

    def list_factor_research_runs(self, **params: Any) -> dict[str, Any]:
        query = {
            key: value for key, value in params.items()
            if value not in (None, "", [], ())
        }
        return self._expect_success(self.session.get(
            "/custom-factors/api/factor-library-research-runs",
            query=query or None,
        ))

    def save_factor_research_run(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/custom-factors/api/factor-library-research-runs",
            payload,
        ))

    def factor_research_metrics(self, **params: Any) -> dict[str, Any]:
        query = {
            key: value for key, value in params.items()
            if value not in (None, "", [], {})
        }
        return self._expect_success(self.session.get(
            "/custom-factors/api/factor-library-research-metrics",
            query=query or None,
        ))

    def factor_research_stability(self, **params: Any) -> dict[str, Any]:
        query = {
            key: value for key, value in params.items()
            if value not in (None, "", [], {})
        }
        return self._expect_success(self.session.get(
            "/custom-factors/api/factor-library-research-stability",
            query=query or None,
        ))

    def group_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._expect_success(
            self.session.post("/get_group_snapshot", payload)
        )

    def group_order_flow(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._expect_success(
            self.session.post("/get_group_order_flow", payload)
        )

    def group_detail(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._expect_success(
            self.session.post("/get_group_detail", payload)
        )

    def group_ranking_detail(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.post("/get_group_ranking_detail", payload)
        )

    def factor_workspace_source_root(self) -> dict[str, Any]:
        return self._expect_success(
            self.session.get("/custom-factors/api/source-root")
        )

    def save_factor_workspace_source_root(
        self,
        source_root: str,
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/custom-factors/api/source-root",
            {"source_root": source_root},
        ))

    def build_factor_workspace(self) -> dict[str, Any]:
        return self._expect_success(
            self.session.post("/custom-factors/api/workspace/build", {})
        )

    def sync_factor_workspace(
        self,
        *,
        branch_mode: str = "force",
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/custom-factors/api/workspace/sync",
            {"branch_mode": branch_mode},
        ))

    def push_factor_workspace(
        self,
        *,
        branch_mode: str = "auto",
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/custom-factors/api/workspace/push",
            {"branch_mode": branch_mode},
        ))

    def factor_workspace_snapshot(self) -> dict[str, Any]:
        return self._expect_success(
            self.session.get("/custom-factors/api/workspace/snapshot")
        )

    def factor_workspace_git_settings(self) -> dict[str, Any]:
        return self._expect_success(
            self.session.get("/custom-factors/api/workspace/git-settings")
        )

    def save_factor_workspace_git_settings(
        self,
        *,
        git_enabled: bool,
        git_repo_root: str,
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/custom-factors/api/workspace/git-settings",
            {
                "git_enabled": git_enabled,
                "git_repo_root": git_repo_root,
            },
        ))

    def factor_workspace_git_action(
        self,
        action: str,
        **payload: Any,
    ) -> dict[str, Any]:
        data = {"action": action, **payload}
        return self._expect_success(
            self.session.post("/custom-factors/api/workspace/git", data)
        )

    def factor_source_sync_manifest(
        self,
        *,
        include_subordinates: bool = True,
    ) -> dict[str, Any]:
        """Read visible factor-source metadata for an explicit local pull."""
        return self._expect_success(self.session.get(
            "/custom-factors/api/source-sync/manifest",
            query={
                "include_subordinates": "1" if include_subordinates else "0",
            },
        ))

    def factor_source_download_access(
        self,
        *,
        object_id: str,
        source_sha256: str,
    ) -> dict[str, Any]:
        """Issue a hash-bound 7997 download capability for one source file."""
        return self._expect_success(self.session.post(
            "/api/transfers/objects/download-access",
            {
                "object_kind": "factor_source",
                "object_id": object_id,
                "source_sha256": source_sha256,
            },
        ))
