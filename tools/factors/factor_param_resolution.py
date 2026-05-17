"""Engine-level seam for resolving serialized FactorParam values."""
from __future__ import annotations

from typing import Any, Callable

_resolver: Callable[[Any], Any] | None = None


def register_factor_param_resolver(resolver: Callable[[Any], Any]) -> None:
    """Register the active adapter used to resolve UI/storage factor references."""
    global _resolver
    _resolver = resolver


def resolve_factor_param_value(value: Any) -> Any:
    """Resolve a serialized FactorParam selection through the registered adapter."""
    if _resolver is None:
        raise RuntimeError(
            "No FactorParam resolver is registered. "
            "Pass a Factor/FactorExpr directly or register an adapter first."
        )
    return _resolver(value)
