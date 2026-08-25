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


@contextmanager
def factor_param_resolver_scope(resolver: Callable[[Any], Any]):
    """Bind a task-local resolver without mutating another request or worker."""
    token = _scoped_resolver.set(resolver)
    try:
        yield
    finally:
        _scoped_resolver.reset(token)
