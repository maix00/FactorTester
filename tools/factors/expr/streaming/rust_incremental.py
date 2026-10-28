"""Compatibility facade from tools.factors expressions to the Rust plan kernel."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from tools.factors.alpha_plan import alpha_plan_spec
from .incremental import UnsupportedStreamingFactor


class UnsupportedByRustPlan(UnsupportedStreamingFactor):
    pass


def shared_factor_plan_spec(expressions: Mapping[str, Any], products: tuple[Any, ...], *, source_freq=None, session_calendar=None, event_line=None):
    if not expressions or not products:
        raise UnsupportedByRustPlan("empty factor set")
    specs = []
    for alias, expression in expressions.items():
        spec = alpha_plan_spec(expression, source_freq=source_freq, products=products, session_calendar=session_calendar)
        if spec is None:
            if type(expression).__name__ == "SignalAlign" and str(expression.signal_freq).lower() in {"1d", "1day", "daily"}:
                raise UnsupportedByRustPlan("daily SignalAlign requires a session-calendar close compiler")
            raise UnsupportedByRustPlan(f"{alias} is not representable by the Rust plan")
        specs.append(spec)

    columns: list[str] = []
    boundaries: list[str] = []
    term_columns: list[str] = []
    nodes: list[dict[str, Any]] = []
    keys: list[str] = []
    outputs: list[int] = []
    by_key: dict[str, int] = {}
    for spec in specs:
        local_columns = list(spec["columns"])
        local_keys = spec.get("keys", [""] * len(spec["nodes"]))
        local_to_global: dict[int, int] = {}
        for local_index, node in enumerate(spec["nodes"]):
            key = local_keys[local_index]
            if key and key in by_key:
                local_to_global[local_index] = by_key[key]
                continue
            node = dict(node)
            for field in ("child", "left", "right", "condition", "when_true", "when_false", "boundary", "trunc_start_child", "trunc_end_child"):
                if field in node and node[field] is not None:
                    node[field] = local_to_global[node[field]]
            if "dependencies" in node:node["dependencies"]=[local_to_global[child] for child in node["dependencies"]]
            if node.get("kind") == "column":
                name = local_columns[node["index"]]
                if name not in columns:
                    columns.append(name)
                node["index"] = columns.index(name)
            elif node.get("kind") == "boundary":
                name = spec["boundaries"][node["index"]]
                if name not in boundaries:
                    boundaries.append(name)
                node["index"] = boundaries.index(name)
            elif node.get("kind") == "term":
                name = spec["term_columns"][node["column"]]
                if name not in term_columns:
                    term_columns.append(name)
                node["column"] = term_columns.index(name)
            local_to_global[local_index] = len(nodes)
            if key:
                by_key[key] = len(nodes)
            keys.append(key)
            nodes.append(node)
        outputs.append(local_to_global[spec["outputs"][0]])
    return {"columns": columns, "keys": keys, "nodes": nodes, "outputs": outputs,
            "boundaries": boundaries, "term_columns": term_columns}, specs


def compile_rust_incremental(expressions: Mapping[str, Any], products: tuple[Any, ...], *, source_freq=None, session_calendar=None, event_line=None):
    from alpha import FactorPlanState
    spec, specs = shared_factor_plan_spec(expressions, products, source_freq=source_freq,
                                           session_calendar=session_calendar)
    state = FactorPlanState(json.dumps(spec), len(products))
    return RustIncrementalExecutor(expressions, products, spec["columns"], state, specs,
                                   len(spec["nodes"]), spec["boundaries"], event_line,
                                   spec["term_columns"])


class _NodePlan:
    def __init__(self, keys):
        self.node_keys = tuple(keys)


class _PlanView:
    def __init__(self, specs):
        self.plans = tuple(_NodePlan(spec.get("key_tuples", [])) for spec in specs)


class RustIncrementalExecutor:
    """Same surface as MultiStreamingIncrementalExecutor, Rust arithmetic."""

    uses_rust = True

    def __init__(self, expressions, products, columns, state, specs, node_count, boundaries=(), event_line=None, term_columns=()) -> None:
        self._aliases = tuple(expressions)
        self._products = tuple(products)
        self._columns = tuple(columns)
        self._state = state
        self._plan = _PlanView(specs)
        self.node_count = node_count
        self._latest: dict[str, dict[Any, float]] = {}
        self._boundaries = tuple(boundaries)
        self._event_line = event_line
        self._event_occurrences = {}
        self._flat = np.zeros(len(products) * max(1, len(columns)), dtype=float)
        self._flags = np.zeros(len(boundaries) * len(products), dtype=np.uint8)
        self._trading_day = None
        self._term_columns = tuple(term_columns)

    def _field(self, fields, name: str) -> float:
        if name in fields:
            return float(fields[name])
        for key, value in fields.items():
            if getattr(key, "name", key) == name:
                return float(value)
        raise ValueError(f"market slice is missing field {name!r}")

    def on_bar(self, timestamp, fields_by_product, term_curves_by_product=None,
               trading_day=None, boundary_flags=None) -> None:
        if set(self._products) - set(fields_by_product):
            raise ValueError("market slice is missing streaming products")
        for product_index, product in enumerate(self._products):
            for column_index, column in enumerate(self._columns):
                self._flat[product_index * len(self._columns) + column_index] = self._field(fields_by_product[product], column)
        for channel, event in enumerate(self._boundaries):
            if boundary_flags is not None and event in boundary_flags:
                flag = boundary_flags[event]
            elif self._event_line is not None:
                from tools.factors.events import EventId
                occurrence = self._event_line.latest(EventId(event))
                if occurrence is None:
                    raise ValueError(f"missing authoritative boundary event {event}")
                flag = occurrence != self._event_occurrences.get(event)
                self._event_occurrences[event] = occurrence
            elif event == "trading_day_start" and trading_day is not None:
                flag = trading_day != self._trading_day
            else:
                raise ValueError(f"missing authoritative boundary event {event}")
            offset = channel * len(self._products)
            if isinstance(flag, Mapping):
                self._flags[offset:offset + len(self._products)] = [bool(flag[product]) for product in self._products]
            else:
                self._flags[offset:offset + len(self._products)].fill(bool(flag))
        stamp = pd.Timestamp(timestamp).value
        curves = []
        if self._term_columns:
            from tools.factors.expr.term_structure_math import normalize_term_curve
            from tools.products.AdjustableTermStructure import TERM_DAYS_TO_MATURITY_COL
            if term_curves_by_product is None or any(product not in term_curves_by_product for product in self._products):
                raise KeyError("TERM_STRUCTURE snapshot is missing curve")
            frames = [normalize_term_curve(term_curves_by_product[product]) for product in self._products]
            for column in self._term_columns:
                for frame in frames:
                    if frame.empty:
                        curves.append([])
                    else:
                        days = frame[TERM_DAYS_TO_MATURITY_COL].to_numpy(dtype=float, copy=False)
                        prices = frame[column].to_numpy(dtype=float, copy=False)
                        curves.append(list(zip(days, prices)))
        raw = np.asarray(self._state.update_context(stamp, self._flat, self._flags, curves)
                         if self._boundaries or self._term_columns else self._state.update_at(stamp, self._flat), dtype=float)
        self._trading_day = trading_day
        matrix = raw.reshape(len(self._aliases), len(self._products))
        self._latest = {
            alias: dict(zip(self._products, matrix[index], strict=True))
            for index, alias in enumerate(self._aliases)
        }

    def on_signal(self, timestamp) -> dict[str, dict[Any, float]]:
        return {alias: dict(values) for alias, values in self._latest.items()}
