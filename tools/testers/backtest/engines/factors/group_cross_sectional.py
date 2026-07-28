"""Streaming execution nodes for Category-partitioned cross-sectional transforms."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(slots=True)
class GroupCrossSectionalNode:
    op: str
    children: tuple[Any, ...]
    category: Any
    products: tuple[Any, ...]

    def update(self, market, cache: dict[int, np.ndarray]) -> np.ndarray:
        values = self.children[0].update(market, cache)
        mask = self.children[1].update(market, cache).astype(bool)
        result = np.full(len(self.products), np.nan, dtype=float)
        for label in self.category.categories:
            positions = np.asarray([
                self.category.is_in_category(label, product) for product in self.products
            ], dtype=bool) & mask & np.isfinite(values)
            series = pd.Series(values[positions], dtype=float)
            if self.op == "cs_group_rank":
                transformed = series.rank(pct=True).to_numpy() - 0.5
            elif self.op == "cs_group_zscore":
                std = series.std()
                transformed = ((series - series.mean()) / std).to_numpy() if std else np.zeros(len(series))
            elif self.op == "cs_group_demean":
                transformed = (series - series.mean()).to_numpy()
            else:
                raise ValueError(f"unknown group cross-sectional op: {self.op}")
            result[positions] = transformed
        return result
