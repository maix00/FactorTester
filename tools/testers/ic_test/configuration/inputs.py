"""Normalize IC authoring selections before immutable compilation."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from tools.factors.formula_identity import is_factor_reference
from tools.factors.factor_set_identity import is_factor_set_reference


def factor_refs(value: Any) -> tuple[str, ...]:
    values = value if isinstance(value, (list, tuple)) else ()
    refs: list[str] = []
    for item in values:
        factor_ref = str(
            item.get("factor_ref") or item.get("target_ref") or ""
        ).strip() if isinstance(item, dict) else str(item or "").strip()
        if not is_factor_reference(factor_ref):
            raise ValueError(
                "each IC core test requires a factor:v2 formula reference"
            )
        refs.append(factor_ref)
    if not refs:
        raise ValueError("IC core tests require at least one frozen factor_ref")
    return unique_texts(refs)


def product_scope_refs(value: Any) -> tuple[str, ...]:
    values = value if isinstance(value, (list, tuple)) else ()
    refs: list[str] = []
    for item in values:
        if isinstance(item, dict):
            ref = str(
                item.get("product_path_selection_id")
                or item.get("selection_id")
                or item.get("id")
                or ""
            ).strip()
        else:
            ref = str(item or "").strip()
        if not ref:
            raise ValueError("each product scope requires a stable selection id")
        refs.append(ref)
    if not refs:
        raise ValueError("IC core tests require at least one product scope")
    return unique_texts(refs)


def factor_set_refs(value: Any) -> tuple[str, ...]:
    values = value if isinstance(value, (list, tuple)) else ()
    refs: list[str] = []
    for item in values:
        target_ref = str(
            item.get("target_ref") or ""
        ).strip() if isinstance(item, dict) else str(item or "").strip()
        if not is_factor_set_reference(target_ref):
            raise ValueError(
                "factor-set selection requires a factor-set:v2 reference"
            )
        refs.append(target_ref)
    return unique_texts(refs)


def entry_delays(value: Any) -> tuple[int, ...]:
    values = value if isinstance(value, (list, tuple)) else (value,)
    result: list[int] = []
    for item in values:
        if isinstance(item, bool):
            raise ValueError("IC entry delays must be non-negative integers")
        try:
            delay = int(item)
        except (TypeError, ValueError) as exc:
            raise ValueError("IC entry delays must be non-negative integers") from exc
        if delay < 0 or delay != item:
            raise ValueError("IC entry delays must be non-negative integers")
        if delay not in result:
            result.append(delay)
    return tuple(result or (0,))


def correlation_methods(value: Any) -> tuple[str, ...]:
    method = str(value or "rank").strip().lower()
    if method == "both":
        return ("pearson", "rank")
    if method not in {"rank", "pearson"}:
        raise ValueError(f"unsupported IC method: {method}")
    return (method,)


def reject_unimplemented_cross_section_settings(
    settings: Mapping[str, Any],
) -> None:
    if str(settings.get("group_adjust") or "off").strip().lower() != "off":
        raise ValueError("group_adjust is not executable and cannot be frozen")
    if str(settings.get("by_group") or "off").strip().lower() != "off":
        raise ValueError("by_group is not executable and cannot be frozen")
    if (
        "min_cross_section_count" in settings
        and settings.get("min_cross_section_count") not in {None, 5, 5.0, "5"}
    ):
        raise ValueError(
            "min_cross_section_count is not executable and cannot be frozen"
        )


def unique_texts(values: Iterable[Any]) -> tuple[str, ...]:
    normalized = {str(item or "").strip() for item in values}
    normalized.discard("")
    return tuple(sorted(normalized))


__all__ = [
    "correlation_methods",
    "entry_delays",
    "factor_refs",
    "factor_set_refs",
    "product_scope_refs",
    "reject_unimplemented_cross_section_settings",
    "unique_texts",
]
