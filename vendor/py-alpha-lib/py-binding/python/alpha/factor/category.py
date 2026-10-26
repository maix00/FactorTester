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

    def __init__(self, category=None, label: str | None = None):
        self.label = label or getattr(category, "alias", None)
        if self.label is None:
            raise ValueError("CategoryBoolRef requires a label")
        if category is not None and self.label not in getattr(category, "categories", ()):
            raise ValueError(f"unknown category label {self.label!r}")
        self.category = category

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
        memberships = getattr(ctx, "categories", None)
        timestamps = index.as_unit("ns").asi8 if isinstance(index, pd.DatetimeIndex) else None
        for product in ctx.products:
            if memberships is not None:
                membership = memberships.get(product) or memberships.get(str(product))
                if isinstance(membership, (tuple, list)):
                    for row, timestamp in enumerate(timestamps if timestamps is not None else [None] * len(index)):
                        active = [item for item in membership if getattr(item, "active_at", lambda _: True)(timestamp)]
                        labels = frozenset().union(*(item.labels for item in active)) if active else frozenset()
                        frame.iloc[row, frame.columns.get_loc(product)] = self.label in labels
                    continue
                labels = getattr(membership, "labels", membership)
                frame[product] = bool(labels) and self.label in labels
            elif self.category is not None:
                frame[product] = self.category.is_in_category(self.label, product)
            else:
                raise ValueError("CategoryBoolRef needs ctx.categories or a category object")
        return frame

    def _evaluate(self, ctx) -> pd.DataFrame:
        return self.evaluate(ctx)
