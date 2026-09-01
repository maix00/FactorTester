"""Structural lookback contracts for factor expression graphs.

The batch evaluator and the incremental evaluator need the same answer to a
simple question: how much history is required before a signal is causal and
fully warmed up?  This module intentionally works on the public shape of the
expression graph instead of importing expression subclasses, which keeps it
usable from both the factor package and backtest modules without introducing a
cycle.

Serial operators add support (``shift(2, rolling(5, x))`` needs 7 units), while
parallel/pointwise operators take the maximum support of their children.  A
``RollingOp`` only traverses its data operands; its window and truncation
parameters are configuration, not data history.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class LookbackContract:
    """Resolved support metadata for one expression subtree.

    ``warmup`` is the conservative serial support from the first usable
    sample.  ``max_window`` is the largest individual rolling/shift window.
    ``serial_depth`` records the deepest chain of serial lookback operators;
    it is useful for diagnostics and does not alter the warm-up result.
    ``unknown`` is true when a window could not be resolved in the requested
    unit (for example a calendar-day window without a frequency).
    """

    warmup: Any | None
    max_window: Any | None
    serial_depth: int
    node_count: int
    unknown: bool = False


def infer_lookback_contract(
    expression: Any,
    *,
    resolve_window: Callable[[Any], Any | None],
    zero: Any,
    add: Callable[[Any, Any], Any],
) -> LookbackContract:
    """Infer a lookback contract for a FactorExpr-shaped object.

    ``resolve_window`` is supplied by the caller so the same traversal can
    resolve time-valued windows for run-window warm-up and bar-valued windows
    for an incremental plan.  Returning ``None`` from it marks that branch as
    unknown; callers should then avoid claiming a smaller warm-up.
    """

    memo: dict[int, LookbackContract] = {}

    def empty() -> LookbackContract:
        return LookbackContract(zero, None, 0, 0, False)

    def parallel(children: tuple[Any, ...]) -> LookbackContract:
        contracts = [visit(child) for child in children if child is not None]
        if not contracts:
            return empty()
        unknown = any(contract.unknown for contract in contracts)
        known_warmups = [contract.warmup for contract in contracts if contract.warmup is not None]
        warmup = None if unknown else (max(known_warmups) if known_warmups else zero)
        windows = [contract.max_window for contract in contracts if contract.max_window is not None]
        return LookbackContract(
            warmup,
            max(windows) if windows else None,
            max(contract.serial_depth for contract in contracts),
            sum(contract.node_count for contract in contracts),
            unknown,
        )

    def serial(window: Any | None, child: LookbackContract) -> LookbackContract:
        unknown = window is None or child.unknown
        warmup = None if unknown else add(window, child.warmup or zero)
        windows = [value for value in (window, child.max_window) if value is not None]
        return LookbackContract(
            warmup,
            max(windows) if windows else None,
            child.serial_depth + 1,
            child.node_count + 1,
            unknown,
        )

    def visit(expr: Any) -> LookbackContract:
        if expr is None:
            return empty()
        key = id(expr)
        if key in memo:
            return memo[key]

        cls_name = type(expr).__name__
        if cls_name == "RollingOp":
            operands = _operands(expr)
            data_start = int(getattr(expr, "_data_start", 1))
            n_data = int(getattr(expr, "_n_data", max(0, len(operands) - data_start)))
            children = tuple(operands[data_start:data_start + n_data])
            child_contract = parallel(children)
            result = serial(resolve_window(getattr(expr, "window", None)), child_contract)
        elif cls_name == "ShiftOp":
            child_contract = visit(getattr(expr, "operand", None))
            result = serial(resolve_window(getattr(expr, "periods", None)), child_contract)
        elif cls_name in {"BarSinceOp", "BarDistanceOp"}:
            operands = _operands(expr)
            child_contract = parallel(operands[:-1])
            scope = getattr(expr, "scope", None)
            window_expr = getattr(scope, "count", None)
            result = serial(
                resolve_window(window_expr) if window_expr is not None else None,
                child_contract,
            )
        else:
            result = parallel(_operands(expr))
            result = LookbackContract(
                result.warmup,
                result.max_window,
                result.serial_depth,
                result.node_count + 1,
                result.unknown,
            )
        memo[key] = result
        return result

    return visit(expression)


def _operands(expression: Any) -> tuple[Any, ...]:
    operands = getattr(expression, "_operands", None)
    if operands is None:
        operands = getattr(expression, "operands", ())
    if operands is None:
        return ()
    try:
        return tuple(operands)
    except TypeError:
        return ()
