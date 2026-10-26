"""Compatibility facade from tools.factors expressions to the Rust plan kernel."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from tools.factors.alpha_plan import alpha_plan_spec


class UnsupportedByRustPlan(Exception):
    pass


def compile_rust_incremental(expressions: Mapping[str, Any], products: tuple[Any, ...]):
    from alpha import FactorPlanState

    if not expressions or not products:
        raise UnsupportedByRustPlan("empty factor set")
    specs = []
    for alias, expression in expressions.items():
        spec = alpha_plan_spec(expression)
        if spec is None:
            raise UnsupportedByRustPlan(f"{alias} is not representable by the Rust plan")
        specs.append(spec)

    columns: list[str] = []
    nodes: list[dict[str, Any]] = []
    keys: list[str] = []
    outputs: list[int] = []
    for spec in specs:
        offset = len(nodes)
        local_columns = list(spec["columns"])
        for node in spec["nodes"]:
            node = dict(node)
            for field in ("child", "left", "right", "condition", "when_true", "when_false"):
                if field in node:
                    node[field] += offset
            if node.get("kind") == "column":
                name = local_columns[node["index"]]
                if name not in columns:
                    columns.append(name)
                node["index"] = columns.index(name)
            nodes.append(node)
        keys.extend(spec.get("keys", [""] * len(spec["nodes"])))
        outputs.append(spec["outputs"][0] + offset)

    state = FactorPlanState(json.dumps({
        "columns": columns, "keys": keys, "nodes": nodes, "outputs": outputs,
    }), len(products))
    return RustIncrementalExecutor(expressions, products, columns, state, specs)


class _NodePlan:
    def __init__(self, keys):
        self.node_keys = tuple(keys)


class _PlanView:
    def __init__(self, specs):
        self.plans = tuple(_NodePlan(spec.get("key_tuples", [])) for spec in specs)


class RustIncrementalExecutor:
    """Same surface as MultiStreamingIncrementalExecutor, Rust arithmetic."""

    uses_rust = True

    def __init__(self, expressions, products, columns, state, specs) -> None:
        self._aliases = tuple(expressions)
        self._products = tuple(products)
        self._columns = tuple(columns)
        self._state = state
        self._plan = _PlanView(specs)
        self._latest: dict[str, dict[Any, float]] = {}

    def _field(self, fields, name: str) -> float:
        if name in fields:
            return float(fields[name])
        for key, value in fields.items():
            if getattr(key, "name", key) == name:
                return float(value)
        raise ValueError(f"market slice is missing field {name!r}")

    def on_bar(self, timestamp, fields_by_product, term_curves_by_product=None,
               trading_day=None) -> None:
        if set(self._products) - set(fields_by_product):
            raise ValueError("market slice is missing streaming products")
        values = [
            self._field(fields_by_product[product], column)
            for product in self._products
            for column in self._columns
        ]
        # The kernel expects one value per product for the compiled column set;
        # multi-column panes use column-major product values.
        flat = np.asarray(values, dtype=float)
        raw = np.asarray(self._state.update_at(pd.Timestamp(timestamp).value, flat), dtype=float)
        matrix = raw.reshape(len(self._aliases), len(self._products))
        self._latest = {
            alias: dict(zip(self._products, matrix[index], strict=True))
            for index, alias in enumerate(self._aliases)
        }

    def on_signal(self, timestamp) -> dict[str, dict[Any, float]]:
        return {alias: dict(values) for alias, values in self._latest.items()}
