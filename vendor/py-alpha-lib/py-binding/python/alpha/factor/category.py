"""Category membership leaves for the public factor API."""

from __future__ import annotations

import pandas as pd

from .core import FactorExpr


class CategoryBoolRef(FactorExpr):
    """Boolean panel: product belongs to ``category[label]``.

    This is a public-API leaf; the Rust plan currently reports it as an
    explicit blocker because category membership needs the plan's product
    universe at compile time.
    """

    def __init__(self, category, label: str):
        if label not in getattr(category, "categories", ()): 
            raise ValueError(f"unknown category label {label!r}")
        self.category = category
        self.label = label

    def _structural_key(self):
        return (
            "alpha.factor.CategoryBoolRef",
            getattr(self.category, "alias", None),
            getattr(self.category, "_definition_key", None),
            self.label,
        )

    def evaluate(self, ctx) -> pd.DataFrame:
        index = next(iter(ctx.preloaded.values())).index if ctx.preloaded else pd.RangeIndex(0)
        frame = pd.DataFrame(index=index, columns=tuple(ctx.products), dtype=bool)
        for product in ctx.products:
            frame[product] = self.category.is_in_category(self.label, product)
        return frame

    def _evaluate(self, ctx) -> pd.DataFrame:
        return self.evaluate(ctx)
