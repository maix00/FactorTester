"""Factor values emitted by streaming FactorExpr evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FactorSignal:
    factor_alias: str
    values: Mapping[str, float]

    def __post_init__(self) -> None:
        if not self.factor_alias:
            raise ValueError("factor signal requires a factor alias")
