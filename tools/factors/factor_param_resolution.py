"""Engine-level seam for resolving serialized FactorParam values."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable

_resolver: Callable[[Any], Any] | None = None
_scoped_resolver: ContextVar[Callable[[Any], Any] | None] = ContextVar(
    "factor_param_resolver", default=None,
)


def register_factor_param_resolver(resolver: Callable[[Any], Any]) -> None:
    """Register the active adapter used to resolve UI/storage factor references."""
    global _resolver
    _resolver = resolver


def resolve_factor_param_value(value: Any) -> Any:
    """Resolve a serialized FactorParam selection through the registered adapter."""
    resolver = _scoped_resolver.get() or _resolver
    if resolver is None:
        raise RuntimeError(
            "No FactorParam resolver is registered. "
            "Pass a Factor/FactorExpr directly or register an adapter first."
        )
    return resolver(value)


def coerce_factor_param_expr(value: Any) -> Any:
    """Normalize a FactorParam value to a FactorExpr when possible.

    Serialized string/dict references remain deferred during declaration and
    are resolved through the active adapter at runtime.  Existing FactorExpr
    semantics, including SignalAlign, are preserved for nested factors.
    """
    from tools.data.types import DataColumn
    from tools.factors.FactorExpr import (
        ColumnRef,
        ConstExpr,
        FactorExpr,
        ParamRef,
    )
    from tools.parameters.DataColumnParam import DataColumnParam

    if value is None:
        return None
    if isinstance(value, (str, dict)):
        try:
            return ColumnRef(DataColumn(value))
        except Exception:
            return value
    if isinstance(value, DataColumnParam):
        return ParamRef(value)

    # Import lazily to avoid the Factor -> FactorExpr module cycle.
    from tools.factors import Factor
    if isinstance(value, Factor):
        return value._expr
    if isinstance(value, FactorExpr):
        return value

    try:
        return ColumnRef(DataColumn(value))
    except Exception:
        return ConstExpr(value)


def resolve_factor_param_expr(value: Any) -> tuple[Any, Any | None]:
    """Resolve a transport reference and return its expression plus source Factor."""
    if isinstance(value, (str, dict)):
        value = resolve_factor_param_value(value)
    from tools.factors import Factor
    source_factor = value if isinstance(value, Factor) else None
    return coerce_factor_param_expr(value), source_factor


@contextmanager
def factor_param_resolver_scope(resolver: Callable[[Any], Any]):
    """Bind a task-local resolver without mutating another request or worker."""
    token = _scoped_resolver.set(resolver)
    try:
        yield
    finally:
        _scoped_resolver.reset(token)
