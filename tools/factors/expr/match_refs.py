"""Context-bound leaves used only inside historical match predicates."""

from __future__ import annotations

from .core import EvaluateContext, FactorExpr


class MatchValueRef(FactorExpr):
    def __init__(self, role: str) -> None:
        if role not in {"current", "candidate"}:
            raise ValueError("match value role must be current or candidate")
        self.role = role

    def _evaluate(self, ctx: EvaluateContext):
        raise ValueError(
            f"{self.role.upper()} is only valid inside FactorExpr.bar_distance condition"
        )

    def resolve(self, *args, **kwargs) -> MatchValueRef:
        return self

    def _structural_key(self) -> tuple:
        return (type(self).__name__, self.role)

    def _to_latex(self, subst=None) -> str:
        return "X_t" if self.role == "current" else "X_{t-k}"

    def _get_alias(self) -> str:
        return self.role.upper()


CURRENT = MatchValueRef("current")
CANDIDATE = MatchValueRef("candidate")

