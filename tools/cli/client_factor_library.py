"""Navigation, factor library, and factor workspace HTTP client methods."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

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
                self.session.get("/api/factor-library/overview", query=params)
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
            "/api/factor-library/families/custom",
            {
                "source_code": source_code,
                "chinese_name": chinese_name,
                "description": description,
                "category": category,
            },
        ))

    def factor_expr_operators(self) -> dict[str, Any]:
        return self._expect_success(
            self.session.get("/api/factor-library/families/operators")
        )

    def custom_factor_catalog(
        self,
        *,
        include_subordinates: bool = False,
    ) -> dict[str, Any]:
        query = {"include_subordinates": "1"} if include_subordinates else None
        return self._expect_success(
            self.session.get("/api/factor-library/families", query=query)
        )

    def validate_factor_expr(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.post("/api/factor-library/families/validate", payload)
        )

    def list_registered_factor_sets(self, *, query: str = "") -> dict[str, Any]:
        params = {"query": query} if query else None
        return self._expect_success(self.session.get(
            "/api/factor-library/factor-sets", query=params,
        ))

    def factor_set_descriptor(self, target_ref: str) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            "/api/factor-library/factor-sets/descriptor",
            query={"target_ref": target_ref},
        ))

    def register_factor_set(self, descriptor: dict[str, Any]) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/api/factor-library/factor-sets",
            {"descriptor": descriptor},
        ))

    def unregister_factor_set(self, target_ref: str) -> dict[str, Any]:
        return self._expect_success(self.session.delete(
            "/api/factor-library/factor-sets",
            query={"target_ref": target_ref},
        ))

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
            "/api/factor-library/overview",
            query=query or None,
        ))

    def factor_catalog(self) -> dict[str, Any]:
        """Read the Manager-owned factor catalog used by Web and Swift."""
        families = self._expect_success(
            self.session.get("/api/factor-library/families")
        )
        factors = self._expect_success(
            self.session.get("/api/factor-library/factors")
        )
        family_scopes = families.get("family_scopes") or {}
        factor_scopes = factors.get("family_scopes") or {}
        scopes = {
            scope: {
                **(family_scopes.get(scope) or {}),
                **(factor_scopes.get(scope) or {}),
                "families": list(
                    (family_scopes.get(scope) or {}).get("families") or []
                ),
                "factors": list(
                    (factor_scopes.get(scope) or {}).get("factors") or []
                ),
            }
            for scope in set(family_scopes) | set(factor_scopes)
        }
        return {**families, **factors, "family_scopes": scopes}

    def factor_set_catalog(self, *, query: str = "") -> dict[str, Any]:
        """Read scoped immutable Factor Sets from the Manager catalog."""
        params = {"query": query} if query else None
        return self._expect_success(self.session.get(
            "/api/factor-library/factor-sets", query=params,
        ))

    def factor_library_source_projection(
        self,
        owner_ref: str,
    ) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            f"/api/factor-library/owners/"
            f"{quote(owner_ref, safe='')}/projection",
        ))

    def factor_library_sources(self) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            "/api/factor-library/owners"
        ))

    def factor_library_configs(
        self,
        factor_family: str,
        *,
        product_group: str = "",
    ) -> dict[str, Any]:
        query = {"product_group": product_group} if product_group else None
        return self._expect_success(self.session.get(
            f"/api/factor-library/configurations/{factor_family}",
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
            f"/api/factor-library/configurations/{factor_family}",
            payload,
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
            self.session.get("/api/factor-library/workspace/user/root")
        )

    def save_factor_workspace_source_root(
        self,
        source_root: str,
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/api/factor-library/workspace/user/root",
            {"source_root": source_root},
        ))

    def sync_factor_workspace(
        self,
        *,
        branch_mode: str = "force",
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/api/factor-library/workspace/user/download",
            {"branch_mode": branch_mode},
        ))

    def push_factor_workspace(
        self,
        *,
        branch_mode: str = "auto",
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            "/api/factor-library/workspace/user/upload",
            {"branch_mode": branch_mode},
        ))

    def merge_factor_workspace_download(self) -> dict[str, Any]:
        return self._expect_success(
            self.session.post(
                "/api/factor-library/workspace/user/merge-download", {}
            )
        )
