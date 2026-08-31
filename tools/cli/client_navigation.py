"""Application navigation HTTP client methods."""

from __future__ import annotations

from typing import Any

from .client_base import ClientMixinBase


class NavigationClientMixin(ClientMixinBase):
    def list_modules(self, parent: str | None = None) -> list[dict[str, Any]]:
        if parent is None:
            return self.home_modules()
        if parent == "products":
            return [
                {
                    "key": key,
                    "label": label,
                    "kind": "module",
                    "has_children": False,
                }
                for key, label in (
                    ("products/info", "产品后端信息"),
                    ("products/product-groups", "产品组库"),
                    ("products/categories", "产品分类库"),
                    ("products/availability", "数据可用性"),
                    ("products/liquidity", "逐产品流动性证据"),
                )
            ]
        data = self._expect_success(self.session.get(
            "/api/test-authoring/modules", query={"parent": parent},
        ))
        if data.get("parent") != parent:
            raise RuntimeError(
                "服务端测试模块导航接口不是分层导航版本，请更新并重启服务端"
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
