"""Field metadata lookup for backtest audit rendering."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AuditFieldMetadata:
    labels: dict[str, str] = field(default_factory=dict)
    tab_order: dict[str, int] = field(default_factory=dict)
    display_order: dict[str, int] = field(default_factory=dict)
    display_offsets: dict[str, int] = field(default_factory=dict)
    value_kinds: dict[str, str] = field(default_factory=dict)

    def label(self, name: str) -> str:
        """Return field name with Chinese label: ``margin_mode (保证金模式)``."""
        cn = self.labels.get(name) or self.labels.get(name.rsplit(".", 1)[-1])
        return f"{name} ({cn})" if cn else name

    def field_label(self, qualified_name: str) -> str:
        field_name = qualified_name.rsplit(".", 1)[-1]
        return f"{self.label(field_name)} [{qualified_name}]"

    def sort_key(self, qualified_name: str) -> tuple[int, int, str]:
        field_name = qualified_name.rsplit(".", 1)[-1]
        display_order = self.display_order.get(qualified_name, self.display_order.get(field_name))
        tab_order = self.tab_order.get(qualified_name, self.tab_order.get(field_name))
        return (
            int(display_order) if display_order is not None else 1_000_000,
            int(tab_order) if tab_order is not None else 1_000_000,
            qualified_name,
        )

    def value_kind(self, qualified_name: str) -> str | None:
        field_name = qualified_name.rsplit(".", 1)[-1]
        return self.value_kinds.get(qualified_name) or self.value_kinds.get(field_name)


def load_field_metadata() -> AuditFieldMetadata:
    """Load audit field metadata from executable module registry.

    Field metadata comes from the backend executable-module registry, not a
    hand-picked controller list.  Adding a registered backtest module
    automatically makes its labels and chip ordering available to the renderer.
    """
    labels: dict[str, str] = {}
    tab_order: dict[str, int] = {}
    display_order: dict[str, int] = {}
    display_offsets: dict[str, int] = {}
    value_kinds: dict[str, str] = {}
    try:
        from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES

        for module_class in _ALL_MODULE_CLASSES:
            if not hasattr(module_class, "fields"):
                continue
            for field_name, field_definition in module_class.fields.items():
                qualified = f"{module_class.__name__}.{field_name}"
                label = getattr(field_definition, "label", "") or ""
                if label:
                    labels[field_name] = label
                    labels[qualified] = label
                tab_order_value = getattr(field_definition, "tab_order", None)
                if tab_order_value is not None:
                    tab_order[field_name] = tab_order_value
                    tab_order[qualified] = tab_order_value
                serialization = getattr(field_definition, "serialization", None) or {}
                if isinstance(serialization, dict) and serialization.get("display_order") is not None:
                    display_order_value = int(serialization["display_order"])
                    display_order[field_name] = display_order_value
                    display_order[qualified] = display_order_value
                offset = getattr(field_definition, "display_offset", 0)
                if offset:
                    display_offsets[field_name] = int(offset)
                    display_offsets[qualified] = int(offset)
                audit_value_kind = getattr(field_definition, "audit_value_kind", None)
                if audit_value_kind:
                    value_kinds[field_name] = str(audit_value_kind)
                    value_kinds[qualified] = str(audit_value_kind)
    except Exception:
        pass
    return AuditFieldMetadata(
        labels=labels,
        tab_order=tab_order,
        display_order=display_order,
        display_offsets=display_offsets,
        value_kinds=value_kinds,
    )
