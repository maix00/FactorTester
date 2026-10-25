"""Streaming per-bar cross-sectional OLS residualization."""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass(slots=True)
class ResidualizeNode:
    children: tuple[object, ...]
    exposure_count: int

    def update(self, market, cache: dict[int, np.ndarray]) -> np.ndarray:
        y = self.children[0].update(market, cache)
        exposures = np.column_stack([
            child.update(market, cache) for child in self.children[1:1 + self.exposure_count]
        ])
        mask = self.children[-1].update(market, cache).astype(bool)
        valid = mask & np.isfinite(y) & np.isfinite(exposures).all(axis=1)
        result = np.full(len(y), np.nan, dtype=float)
        if valid.sum() <= self.exposure_count + 1:
            return result
        design = np.column_stack([np.ones(valid.sum()), exposures[valid]])
        beta, *_ = np.linalg.lstsq(design, y[valid], rcond=None)
        result[valid] = y[valid] - design @ beta
        return result
