"""Streaming execution nodes for Category-partitioned cross-sectional transforms."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .cross_sectional_kernels import demean, rank_percent, zscore


@dataclass(slots=True)
class GroupCrossSectionalNode:
    op: str
    children: tuple[Any, ...]
    category: Any
    products: tuple[Any, ...]
    _category_positions: tuple[tuple[Any, np.ndarray], ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # Category membership is static for a compiled run.  Materialize the
        # boolean positions once instead of calling is_in_category for every
        # category on every bar.
        self._category_positions = tuple(
            (
                label,
                np.asarray(
                    [self.category.is_in_category(label, product) for product in self.products],
                    dtype=bool,
                ),
            )
            for label in self.category.categories
        )

    def update(self, market, cache: dict[int, np.ndarray]) -> np.ndarray:
        key = id(self)
        if key in cache:
            return cache[key]
        values = self.children[0].update(market, cache)
        mask = self.children[1].update(market, cache).astype(bool)
        result = np.full(len(self.products), np.nan, dtype=float)
        for _label, category_positions in self._category_positions:
            positions = category_positions & mask & np.isfinite(values)
            if self.op == "cs_group_rank":
                transformed = rank_percent(values, positions)[positions]
            elif self.op == "cs_group_zscore":
                transformed = zscore(values, positions)[positions]
            elif self.op == "cs_group_demean":
                transformed = demean(values, positions)[positions]
            else:
                raise ValueError(f"unknown group cross-sectional op: {self.op}")
            result[positions] = transformed
        cache[key] = result
        return result
