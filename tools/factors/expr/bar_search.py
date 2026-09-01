"""Event-distance and current-versus-history bar search expressions."""

from __future__ import annotations

from typing import Any, Literal, cast

import pandas as pd

from .bar_search_eval import evaluate_bar_distance, evaluate_bar_since, scalar_default
from .core import EvaluateContext, FactorExpr
from .leaf import _to_expr
from .lookback_scope import BarCountScope, LookbackScope
from .operands import OperandExpr

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

    def _to_latex(self, subst: dict | None = None) -> str:
        return r"\operatorname{ScopeLength}"

    def _get_alias(self) -> str:
        return "SCOPE_LENGTH"


SCOPE_LENGTH = ScopeLengthDefault()


def _validate_select(select: str) -> Selection:
    if select not in {"nearest", "farthest"}:
        raise ValueError("bar search select must be 'nearest' or 'farthest'")
    return cast(Selection, select)


class BarSinceOp(OperandExpr):
    def __init__(
        self,
        condition: FactorExpr,
        *,
        scope: LookbackScope,
        select: str = "nearest",
        default: Any = SCOPE_LENGTH,
        include_current: bool = True,
    ) -> None:
        super().__init__("bar_since", condition, _to_expr(default))
        self.scope = scope
        self.select = _validate_select(select)
        self.include_current = bool(include_current)

    @property
    def condition(self) -> FactorExpr:
        return self.operands[0]

    @property
    def _operands(self) -> tuple[FactorExpr, ...]:
        scope_refs = (self.scope.count,) if isinstance(self.scope, BarCountScope) else ()
        return (*self.operands, *scope_refs)

    def _evaluate(self, ctx: EvaluateContext) -> pd.DataFrame:
        condition = self.condition.evaluate(ctx=ctx)
        return evaluate_bar_since(
            condition,
            scope=self.scope,
            select=self.select,
            default=scalar_default(self.operands[1]),
            ctx=ctx,
            include_current=self.include_current,
        )

    def resolve(self, *args: Any, **kwargs: Any) -> FactorExpr:
        resolved: FactorExpr = BarSinceOp(
            self.condition.resolve(*args, **kwargs),
            scope=self.scope.resolve(*args, **kwargs),
            select=self.select,
            default=self.operands[1].resolve(*args, **kwargs),
            include_current=self.include_current,
        )
        if self._is_intermediate:
            resolved = resolved.as_intermediate(
                self._intermediate_name, factor=kwargs.get("caller"),
            )
        return resolved

    def _structural_extra(self) -> tuple[Any, ...]:
        return (self.scope.structural_key(), self.select, self.include_current)

    def _to_latex(self, subst: dict | None = None) -> str:
        condition = self.condition._to_latex(subst)
        return (
            f"\\operatorname{{BarSince}}^{{\\mathrm{{{self.select}}}}}"
            f"_{{{self.scope.to_latex(subst)}}}\\left({condition}\\right)"
        )

    def _get_alias(self) -> str:
        return f"BAR_SINCE_{self.select.upper()}_{self.condition._get_alias()}"


def bar_since(
    condition: Any,
    *,
    scope: LookbackScope,
    select: str = "nearest",
    default: Any = SCOPE_LENGTH,
    include_current: bool = True,
) -> BarSinceOp:
    if not isinstance(scope, LookbackScope):
        raise TypeError(
            "bar_since scope must be created by "
            "scope_bars/scope_session/scope_trading_day"
        )
    return BarSinceOp(
        _to_expr(condition),
        scope=scope,
        select=select,
        default=default,
        include_current=include_current,
    )


class BarDistanceOp(OperandExpr):
    def __init__(
        self,
        value: FactorExpr,
        condition: FactorExpr,
        *,
        scope: LookbackScope,
        select: str = "nearest",
        default: Any = SCOPE_LENGTH,
    ) -> None:
        super().__init__("bar_distance", value, condition, _to_expr(default))
        self.scope = scope
        self.select = _validate_select(select)

    @property
    def value(self) -> FactorExpr:
        return self.operands[0]

    @property
    def condition(self) -> FactorExpr:
        return self.operands[1]

    @property
    def _operands(self) -> tuple[FactorExpr, ...]:
        scope_refs = (self.scope.count,) if isinstance(self.scope, BarCountScope) else ()
        return (*self.operands, *scope_refs)

    def _evaluate(self, ctx: EvaluateContext) -> pd.DataFrame:
        values = self.value.evaluate(ctx=ctx)
        return evaluate_bar_distance(
            values,
            self.condition,
            scope=self.scope,
            select=self.select,
            default=scalar_default(self.operands[2]),
            ctx=ctx,
        )

    def resolve(self, *args: Any, **kwargs: Any) -> FactorExpr:
        resolved: FactorExpr = BarDistanceOp(
            self.value.resolve(*args, **kwargs),
            self.condition.resolve(*args, **kwargs),
            scope=self.scope.resolve(*args, **kwargs),
            select=self.select,
            default=self.operands[2].resolve(*args, **kwargs),
        )
        if self._is_intermediate:
            resolved = resolved.as_intermediate(
                self._intermediate_name, factor=kwargs.get("caller"),
            )
        return resolved

    def _structural_extra(self) -> tuple[Any, ...]:
        return (self.scope.structural_key(), self.select)

    def _to_latex(self, subst: dict | None = None) -> str:
        value = self.value._to_latex(subst)
        condition = self.condition._to_latex(subst)
        return (
            f"\\operatorname{{BarDistance}}^{{\\mathrm{{{self.select}}}}}"
            f"_{{{self.scope.to_latex(subst)}}}"
            f"\\left({value};{condition}\\right)"
        )

    def _get_alias(self) -> str:
        return f"BAR_DISTANCE_{self.select.upper()}_{self.value._get_alias()}"


def bar_distance(
    value: Any,
    condition: Any,
    *,
    scope: LookbackScope,
    select: str = "nearest",
    default: Any = SCOPE_LENGTH,
) -> BarDistanceOp:
    if not isinstance(scope, LookbackScope):
        raise TypeError(
            "bar_distance scope must be created by "
            "scope_bars/scope_session/scope_trading_day"
        )
    return BarDistanceOp(
        _to_expr(value),
        _to_expr(condition),
        scope=scope,
        select=select,
        default=default,
    )
