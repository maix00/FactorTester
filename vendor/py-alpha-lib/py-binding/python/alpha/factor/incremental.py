"""Incremental FactorPlan backed by the same Rust kernel as the bridge."""

from __future__ import annotations

import json

import numpy as np

from .spec import to_plan_spec


class IncrementalFactorPlan:
    def __init__(self, expressions: dict[str, object], products: tuple[str, ...]):
        self.aliases = tuple(expressions)
        self.products = tuple(products)
        spec = to_plan_spec(list(expressions.values()))
        if spec is None:
            raise ValueError("factor expressions cannot be compiled to the Rust plan")
        from alpha import FactorPlanState
        self._state = FactorPlanState(json.dumps(spec), len(self.products))
        self._outputs = tuple(spec["outputs"])

    def update(self, values: list[float] | np.ndarray) -> dict[str, dict[str, float]]:
        array = np.asarray(values, dtype=float)
        if array.shape != (len(self.products),):
            raise ValueError("incremental plan requires one value per product")
        flat = np.asarray(self._state.update(np.ascontiguousarray(array)), dtype=float)
        matrix = flat.reshape(len(self.aliases), len(self.products))
        return {
            alias: dict(zip(self.products, matrix[index], strict=True))
            for index, alias in enumerate(self.aliases)
        }
