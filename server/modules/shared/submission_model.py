"""Backend objects for page-level product path submissions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from server.modules.shared.submission_helpers import resolve_products_from_paths


@dataclass(slots=True)
class ProductPathSelection:
    """A frontend submission: one named product/path universe on a page.

    This object deliberately owns path/product semantics only.  Test-specific
    objects such as IC testers or group testers create their own FactorTester
    contexts when they run.
    """

    selection_id: str
    selected_paths: list[str]
    label: str = ""
    product_group: str = ""
    product_group_template_id: str = ""
    source_type: str = "manual_selection"
    source_key: str = ""
    page_uuid: str = ""
    _products: list[Any] = field(default_factory=list, repr=False)

    @classmethod
    def from_paths(
        cls,
        selection_id: str,
        selected_paths: Sequence[str],
        *,
        label: str = "",
        product_group: str = "",
        product_group_template_id: str = "",
        source_type: str = "manual_selection",
        source_key: str = "",
        page_uuid: str = "",
    ) -> "ProductPathSelection":
        canonical_paths, products = resolve_products_from_paths(list(selected_paths))
        if not canonical_paths:
            raise AssertionError("未选择任何产品路径")
        return cls(
            selection_id=str(selection_id),
            selected_paths=canonical_paths,
            label=str(label or ""),
            product_group=str(product_group or ""),
            product_group_template_id=str(product_group_template_id or ""),
            source_type=str(source_type or "manual_selection"),
            source_key=str(source_key or product_group_template_id or product_group or selection_id or ""),
            page_uuid=str(page_uuid or ""),
            _products=list(products),
        )

    @classmethod
    def from_product_group_template(
        cls,
        selection_id: str,
        template: dict[str, Any],
        *,
        page_uuid: str = "",
    ) -> "ProductPathSelection":
        name = str(template.get("name") or template.get("product_group") or "")
        template_id = str(template.get("id") or template.get("product_group_template_id") or "").strip()
        paths = list(template.get("paths") or template.get("selected_paths") or [])
        if not name:
            raise AssertionError("产品组模板缺少名称")
        if not template_id:
            raise AssertionError("产品组模板缺少 id")
        return cls.from_paths(
            selection_id,
            paths,
            label=name,
            product_group=name,
            product_group_template_id=template_id,
            source_type="user_product_group_template",
            source_key=template_id,
            page_uuid=page_uuid,
        )

    @classmethod
    def from_tester(cls, tester: Any) -> "ProductPathSelection":
        selection = getattr(tester, "product_selection", None)
        if isinstance(selection, cls):
            return selection
        return cls(
            selection_id=_core_submission_id(getattr(tester, "alias", "")),
            selected_paths=list(getattr(tester, "selected_paths", None) or []),
            label=str(getattr(tester, "label", "") or ""),
            product_group=str(getattr(tester, "product_group", "") or ""),
            product_group_template_id=str(getattr(tester, "product_group_template_id", "") or ""),
            source_type=str(getattr(tester, "selection_source_type", "") or "legacy_factor_tester"),
            source_key=str(getattr(tester, "selection_source_key", "") or ""),
            page_uuid=str(getattr(tester, "_page_uuid", "") or ""),
            _products=sorted(
                list(getattr(tester, "products", None) or []),
                key=lambda product: getattr(product, "name", str(product)),
            ),
        )

    @property
    def products(self) -> list[Any]:
        if not self._products and self.selected_paths:
            _, products = resolve_products_from_paths(self.selected_paths)
            self._products = list(products)
        return list(self._products)

    def to_submission_dict(self) -> dict[str, Any]:
        return {
            "id": self.selection_id,
            "product_path_selection_id": self.selection_id,
            "selected_paths": list(self.selected_paths),
            "paths": list(self.selected_paths),
            "label": self.label,
            "product_group": self.product_group,
            "product_group_template_id": self.product_group_template_id,
            "source_type": self.source_type,
            "source_key": self.source_key,
        }

    def to_product_path_selection_dict(self) -> dict[str, Any]:
        return self.to_submission_dict()


def _core_submission_id(alias: str) -> str:
    return alias.split(":", 1)[-1] if ":" in str(alias) else str(alias)
