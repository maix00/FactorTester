"""Factor families and versioned factor identities owned by the public API."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any, ClassVar, Mapping

from .core import FactorExpr, ParamRef, _to_expr


def _digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return base64.urlsafe_b64encode(hashlib.sha256(encoded.encode("utf-8")).digest()).decode("ascii")[:43]


@dataclass(frozen=True)
class FactorIdentity:
    owner_ref: str
    family_alias: str
    factor_alias: str
    semantic_fingerprint: str

    @property
    def family_ref(self) -> str:
        return "factor-family:v2:" + _digest({
            "family_alias": self.family_alias,
            "family_formula_fingerprint": self.semantic_fingerprint,
            "owner_ref": self.owner_ref,
        })

    @property
    def factor_ref(self) -> str:
        return "factor:v2:" + _digest({
            "factor_alias": self.factor_alias,
            "family_alias": self.family_alias,
            "family_formula_fingerprint": self.semantic_fingerprint,
            "owner_ref": self.owner_ref,
            "self_formula_fingerprint": self.semantic_fingerprint,
        })


@dataclass(frozen=True)
class FactorDefinition:
    alias: str
    expression: FactorExpr
    identity: FactorIdentity

    @property
    def ref(self) -> str:
        return self.identity.factor_ref

    def evaluate(self, ctx):
        return self.expression.evaluate(ctx)


class FactorFamily:
    """Parameterised expression template; FactorExpr is the public surface."""

    alias: ClassVar[str] = ""
    params: ClassVar[tuple[Any, ...]] = ()

    @staticmethod
    def factor_expr() -> FactorExpr:
        raise NotImplementedError

    @classmethod
    def get_factor(cls, *, owner_ref: str = "public", alias: str | None = None,
                   values: Mapping[str, Any] | None = None) -> FactorDefinition:
        expression = cls.factor_expr()
        expression = _resolve_params(expression, values or {})
        family_alias = cls.alias or cls.__name__
        factor_alias = alias or family_alias
        identity = FactorIdentity(
            owner_ref=owner_ref,
            family_alias=family_alias,
            factor_alias=factor_alias,
            semantic_fingerprint=expression.semantic_fingerprint(),
        )
        return FactorDefinition(factor_alias, expression, identity)


def _resolve_params(expression: FactorExpr, values: Mapping[str, Any]) -> FactorExpr:
    if isinstance(expression, ParamRef):
        return expression.resolve(values)
    for attribute in ("data", "operand", "condition", "when_true", "when_false"):
        child = getattr(expression, attribute, None)
        if isinstance(child, FactorExpr):
            setattr(expression, attribute, _resolve_params(child, values))
    operands = getattr(expression, "operands", None)
    if operands:
        expression.operands = tuple(_resolve_params(item, values) for item in operands)
    return expression
