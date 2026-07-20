"""Navigation, factor library, and factor workspace HTTP client methods."""

from __future__ import annotations

from typing import Any

from .client_base import ClientMixinBase


class FactorLibraryClientMixin(ClientMixinBase):
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
                    "key": "products/availability",
                    "label": "数据可用性",
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
        if kind in {
            "product_path_selection",
            "product_path_candidates",
            "product_path_selections",
        }:
            data = self._expect_success(
                self.session.get("/api/product-groups", query=params)
            )
            for key in ("product_groups", "items", "selections", "groups"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
            return []
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
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.post(
                "/api/product-groups",
                {"name": name, "paths": paths},
            )
        )

    def product_fields(self, name: str) -> dict[str, Any]:
        return self._expect_success(
            self.session.get("/api/product_fields", query={"name": name})
        )

    def data_availability(
        self,
        *,
        products: list[str] | tuple[str, ...],
        sources: list[str] | tuple[str, ...],
        probe: bool = False,
        expanded: bool = False,
    ) -> dict[str, Any]:
        """Inspect only the explicitly requested market-data scope."""
        return self._expect_success(self.session.post(
            "/api/data-availability",
            {
                "products": list(products),
                "sources": list(sources),
                "probe": bool(probe),
                "expanded": bool(expanded),
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
