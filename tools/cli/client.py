"""High-level FactorTester HTTP API client."""

from __future__ import annotations

from typing import Any

from .http import HttpSession


class FactorTesterClient:
    def __init__(self, session: HttpSession) -> None:
        self.session = session

    def login(self, username: str, password: str) -> dict[str, Any]:
        return self._expect_success(self.session.post("/login", {"username": username, "password": password}))

    def bootstrap_page(self, *, factor: str | None = None, factor_type: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if factor:
            payload["factor"] = factor
        if factor_type:
            payload["type"] = factor_type
        return self._expect_success(self.session.post("/api/single_factor_test/page", payload))

    def list_modules(self, parent: str | None = None) -> list[dict[str, Any]]:
        if parent is None:
            return self.home_modules()
        if parent == "products":
            return [{"key": "products/product-groups", "label": "产品组库", "kind": "module", "has_children": False}]
        if parent == "custom_factors":
            return [{"key": "custom_factors/factor-library", "label": "因子库", "kind": "module", "has_children": False}]
        query = {"parent": parent} if parent else None
        data = self._expect_success(self.session.get("/api/testers/modules", query=query))
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
        return self._expect_success(self.session.get(f"/api/backtest/settings/{application}"))

    def tab_manifest(self, application: str, tab_key: str) -> dict[str, Any]:
        return self._expect_success(self.session.get(f"/api/backtest/settings/{application}/tabs/{tab_key}"))

    def list_candidates(self, kind: str, **params: Any) -> list[dict[str, Any]]:
        if kind in {"product_path_selection", "product_path_candidates", "product_path_selections"}:
            data = self._expect_success(self.session.get("/api/product-groups", query=params))
            for key in ("product_groups", "items", "selections", "groups"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
            return []
        if kind in {"factor", "factor_candidates", "factor_selections"}:
            data = self._expect_success(self.session.get("/api/factor-library-overview", query=params))
            for key in ("factors", "items", "configs", "families"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
            return []
        raise ValueError(f"CLI 暂不支持候选列表类型: {kind}")

    def add_candidate(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if kind in {"factor", "factor_candidates", "factor_selections"}:
            return self._expect_success(self.session.post("/add_factor_by_params", payload))
        raise ValueError(f"CLI 暂不支持新增候选类型: {kind}")

    def create_product_group(self, *, name: str, paths: list[str]) -> dict[str, Any]:
        return self._expect_success(self.session.post("/api/product-groups", {"name": name, "paths": paths}))

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
        return self._expect_success(self.session.get("/api/factor-library-overview", query=query or None))

    def factor_library_configs(self, factor_family: str, *, product_group: str = "") -> dict[str, Any]:
        query = {"product_group": product_group} if product_group else None
        return self._expect_success(self.session.get(f"/api/factor-library-configs/{factor_family}", query=query))

    def save_factor_library_config(
        self,
        factor_family: str,
        *,
        product_group: str,
        params_list: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.put(
                f"/api/factor-library-configs/{factor_family}",
                {"product_group": product_group, "params_list": params_list},
            )
        )

    def _expect_success(self, data: dict[str, Any]) -> dict[str, Any]:
        if data.get("success") is False:
            raise RuntimeError(str(data.get("error") or data))
        return data
