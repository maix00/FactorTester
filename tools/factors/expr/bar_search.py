"""Event-distance and current-versus-history bar search expressions."""

from __future__ import annotations

from typing import Any, Literal, cast

import pandas as pd

from .bar_search_eval import scalar_default
from alpha.factor.annotations import copy_annotation

from .core import EvaluateContext, FactorExpr
from .leaf import _to_expr
from .lookback_scope import BarCountScope, LookbackScope
from .operands import OperandExpr
from .window_semantics import DEFAULT_NAN_POLICY, NanPolicy

Selection = Literal["nearest", "farthest"]




class ScopeLengthDefault(FactorExpr):
    """Marker meaning an unmatched search returns its current scope age."""

    def _evaluate(self, ctx: EvaluateContext) -> pd.DataFrame:
        raise RuntimeError("scope-length default is evaluated by its bar-search operator")

    def _structural_key(self) -> tuple[str]:
        return ("ScopeLengthDefault",)

    @property
    def op_name(self) -> str:
        return "scope_length"


    def _get_alias(self) -> str:
        return "SCOPE_LENGTH"


SCOPE_LENGTH = ScopeLengthDefault()


def _validate_select(select: str) -> Selection:
    if select not in {"nearest", "farthest"}:
        raise ValueError("bar search select must be 'nearest' or 'farthest'")
    return cast(Selection, select)


class BarSinceOp(OperandExpr):
    _rust_only = True

    def __init__(
        self,
        condition: FactorExpr,
        *,
        scope: LookbackScope | None = None,
        lookback: Any = None,
        select: str = "nearest",
        default: Any = SCOPE_LENGTH,
        include_current: bool = True,
        nan_policy: NanPolicy = DEFAULT_NAN_POLICY,
    ) -> None:
        super().__init__("bar_since", condition, _to_expr(default))
        self.scope = scope
        self.lookback = None if lookback is None else _to_expr(lookback)
        self.select = _validate_select(select)
        self.include_current = bool(include_current)
        self.nan_policy = nan_policy

    @property
    def condition(self) -> FactorExpr:
        return self.operands[0]

    @property
    def _operands(self) -> tuple[FactorExpr, ...]:
        scope_refs = (self.scope.count,) if isinstance(self.scope, BarCountScope) else ()
        return (*self.operands, *scope_refs, *((self.lookback,) if self.lookback is not None else ()))

    def _evaluate(self, ctx: EvaluateContext) -> pd.DataFrame:
        from .rust_plan import evaluate_rust_plan
        result=evaluate_rust_plan([self],ctx)
        if result is None:raise TypeError('bar search requires Rust expressions or explicit DataFrame inputs')
        return result[0]

    def resolve(self, *args: Any, **kwargs: Any) -> FactorExpr:
        resolved: FactorExpr = BarSinceOp(
            self.condition.resolve(*args, **kwargs),
            scope=None if self.scope is None else self.scope.resolve(*args, **kwargs),
            lookback=None if self.lookback is None else self.lookback.resolve(*args, **kwargs),
            select=self.select,
            default=self.operands[1].resolve(*args, **kwargs),
            include_current=self.include_current,
            nan_policy=self.nan_policy,
        )
        return copy_annotation(self,resolved)

    def _structural_extra(self) -> tuple[Any, ...]:
        return ("partition-search:v2", None if self.scope is None else self.scope.structural_key(),
                None if self.lookback is None else self.lookback._structural_key(), self.select, self.include_current,
                self.nan_policy.value)


    def _get_alias(self) -> str:
        return f"BAR_SINCE_{self.select.upper()}_{self.condition._get_alias()}"


def bar_since(
    condition: Any,
    *,
    scope: LookbackScope | None = None,
    lookback: Any = None,
    select: str = "nearest",
    default: Any = SCOPE_LENGTH,
    include_current: bool = True,
    nan_policy: NanPolicy = DEFAULT_NAN_POLICY,
) -> BarSinceOp:
    if scope is None and lookback is None:raise ValueError("bar search needs a partition scope or explicit lookback")
    if scope is not None and not isinstance(scope, LookbackScope):
        raise TypeError(
            "bar_since scope must be created by "
            "scope_bars/scope_session/scope_trading_day"
        )
    return BarSinceOp(
        _to_expr(condition),
        scope=scope,lookback=lookback,
        select=select,
        default=default,
        include_current=include_current,
        nan_policy=nan_policy,
    )


class BarDistanceOp(OperandExpr):
    _rust_only = True

    def __init__(
        self,
        value: FactorExpr,
        condition: FactorExpr,
        *,
        scope: LookbackScope | None = None,
        lookback: Any = None,
        select: str = "nearest",
        default: Any = SCOPE_LENGTH,
        nan_policy: NanPolicy = DEFAULT_NAN_POLICY,
    ) -> None:
        super().__init__("bar_distance", value, condition, _to_expr(default))
        self.scope = scope
        self.lookback = None if lookback is None else _to_expr(lookback)
        self.select = _validate_select(select)
        self.nan_policy = nan_policy

    @property
    def value(self) -> FactorExpr:
        return self.operands[0]

    @property
    def condition(self) -> FactorExpr:
        return self.operands[1]

    @property
    def _operands(self) -> tuple[FactorExpr, ...]:
        scope_refs = (self.scope.count,) if isinstance(self.scope, BarCountScope) else ()
        return (*self.operands, *scope_refs, *((self.lookback,) if self.lookback is not None else ()))

    def _evaluate(self, ctx: EvaluateContext) -> pd.DataFrame:
        from .rust_plan import evaluate_rust_plan
        result=evaluate_rust_plan([self],ctx)
        if result is None:raise TypeError('bar search requires Rust expressions or explicit DataFrame inputs')
        return result[0]

    def resolve(self, *args: Any, **kwargs: Any) -> FactorExpr:
        resolved: FactorExpr = BarDistanceOp(
            self.value.resolve(*args, **kwargs),
            self.condition.resolve(*args, **kwargs),
            scope=None if self.scope is None else self.scope.resolve(*args, **kwargs),
            lookback=None if self.lookback is None else self.lookback.resolve(*args, **kwargs),
            select=self.select,
            default=self.operands[2].resolve(*args, **kwargs),
            nan_policy=self.nan_policy,
        )
        return copy_annotation(self,resolved)

    def _structural_extra(self) -> tuple[Any, ...]:
        return ("partition-search:v2", None if self.scope is None else self.scope.structural_key(),
                None if self.lookback is None else self.lookback._structural_key(), self.select, self.nan_policy.value)


    def _get_alias(self) -> str:
        return f"BAR_DISTANCE_{self.select.upper()}_{self.value._get_alias()}"


def bar_distance(
    value: Any,
    condition: Any,
    *,
    scope: LookbackScope | None = None,
    lookback: Any = None,
    select: str = "nearest",
    default: Any = SCOPE_LENGTH,
    nan_policy: NanPolicy = DEFAULT_NAN_POLICY,
) -> BarDistanceOp:
    if scope is None and lookback is None:raise ValueError("bar search needs a partition scope or explicit lookback")
    if scope is not None and not isinstance(scope, LookbackScope):
        raise TypeError(
            "bar_distance scope must be created by "
            "scope_bars/scope_session/scope_trading_day"
        )
    return BarDistanceOp(
        _to_expr(value),
        _to_expr(condition),
        scope=scope,lookback=lookback,
        select=select,
        default=default,
        nan_policy=nan_policy,
    )
