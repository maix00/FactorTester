"""Engine-level evaluation progress hooks.

The factor engine owns the hook seam; HTTP/SSE adapters may subscribe to it,
but core evaluation code must not import server modules directly.
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Iterable, Sequence

from tools.factors.FactorExpr import FactorExpr

_lock = threading.Lock()
_completed: int = 0
_total: int = 0
_callback: Callable[[int, int], None] | None = None


def setup(total: int, callback: Callable[[int, int], None]) -> None:
    """Initialize the shared progress counter for one evaluation run."""
    global _completed, _total, _callback
    with _lock:
        _completed = 0
        _total = total
        _callback = callback


def teardown() -> None:
    """Clear progress state after an evaluation run."""
    global _completed, _total, _callback
    with _lock:
        _completed = 0
        _total = 0
        _callback = None


def bump() -> None:
    """Increment progress after one expression node finishes evaluating."""
    global _completed, _total, _callback
    cb = None
    completed = 0
    total = 0
    with _lock:
        _completed += 1
        completed = _completed
        total = _total
        cb = _callback
    if cb is not None:
        cb(completed, total)


def count_nodes(expr: FactorExpr) -> int:
    """Count unique expression nodes by structural key."""
    return count_nodes_many((expr,))


def count_nodes_many(exprs: Iterable[FactorExpr]) -> int:
    """Count the structural-key union for roots sharing one evaluation cache."""
    seen: set = set()
    stack = list(exprs)
    count = 0
    while stack:
        node = stack.pop()
        sk = node._structural_key()
        if sk in seen:
            continue
        seen.add(sk)
        count += 1
        operands = getattr(node, "_operands", getattr(node, "operands", ()))
        for opnd in reversed(list(operands)):
            stack.append(opnd)
    return count


def count_evaluation_nodes(factors: Sequence[Any]) -> int:
    """Count cache misses using the same policy as batch factor evaluation."""
    from tools.factors.evaluation import shared_cache_keys_for_factors

    shared_keys = shared_cache_keys_for_factors(factors)
    cached: set = set()

    def visit(node: FactorExpr) -> int:
        key = node._structural_key()
        cacheable = bool(getattr(node, "_is_intermediate", False)) or key in shared_keys
        if cacheable and key in cached:
            return 0
        count = sum(visit(child) for child in getattr(node, "_operands", ())) + 1
        if cacheable:
            cached.add(key)
        return count

    return sum(visit(factor._expr) for factor in factors)
