"""The scheduler — FlowRegistry (collects Flow/FlowBinding definitions),
sort_and_validate (per-(phase, event_kind) ordering + dependency
checks), FlowContext (per-dispatch-batch scratch), EventQueue (priority
queue, batches same (timestamp, kind)), and run() (wires it all together).

The scheduler never hardcodes business logic — it only knows Phase/Flow/
EventKind/FieldRef shapes, not what any specific module computes.
"""

from __future__ import annotations

import heapq
import itertools
import math
import warnings
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, fields as dataclass_fields, is_dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Protocol, cast

from .timer_events import TimerCancel, TimerEvent, TimerSchedule


_AUDIT_MISSING = object()
_AUDIT_MAX_FULL_SERIES_LENGTH = 20
_AUDIT_MAX_FULL_FRAME_ROWS = 20
_AUDIT_MAX_FULL_FRAME_CELLS = 200
_AUDIT_MAX_FULL_FRAME_COLUMNS = 20
_AUDIT_MAX_FULL_MAPPING_SEQUENCE_ITEMS = 6
_AUDIT_MAX_FULL_SEQUENCE_ITEMS = 100
_AUDIT_EDGE_SAMPLE_ROWS = 3
_AUDIT_EDGE_SAMPLE_COLUMNS = 5
_AUDIT_EDGE_SAMPLE_ITEMS = 3
_CONTRACT_METADATA_FIELD = "TermStructureExpandModule.contract_metadata"
_PRICE_TABLES_FIELD = "MarketDataModule.price_tables"


def _audit_index_bounds(index: Any, *, key_labels: Mapping[str, str] | None = None) -> dict[str, Any]:
    if len(index) == 0:
        return {"start": None, "end": None}
    return {
        "start": _audit_value(index[0], key_labels=key_labels),
        "end": _audit_value(index[-1], key_labels=key_labels),
    }


def _audit_series_sample(
    value: "pd.Series",
    *,
    key_labels: Mapping[str, str] | None = None,
    rows: int = _AUDIT_EDGE_SAMPLE_ROWS,
) -> dict[str, Any]:
    def _slice_payload(sample: "pd.Series") -> dict[str, Any]:
        return {
            "index": [_audit_value(item, key_labels=key_labels) for item in sample.index.tolist()],
            "values": [_audit_value(item, key_labels=key_labels) for item in sample.tolist()],
        }

    if len(value) <= rows * 2:
        return {"head": _slice_payload(value)}
    return {
        "head": _slice_payload(value.head(rows)),
        "tail": _slice_payload(value.tail(rows)),
    }


def _audit_frame_rows(
    value: "pd.DataFrame",
    *,
    key_labels: Mapping[str, str] | None = None,
) -> list[list[Any]]:
    return [
        [_audit_value(item, key_labels=key_labels) for item in row]
        for row in value.itertuples(index=False, name=None)
    ]


def _audit_frame_column_payload(
    value: "pd.DataFrame",
    *,
    key_labels: Mapping[str, str] | None = None,
) -> tuple[Any, "pd.DataFrame"]:
    if len(value.columns) <= _AUDIT_MAX_FULL_FRAME_COLUMNS:
        return (
            [_audit_value(column, key_labels=key_labels) for column in value.columns.tolist()],
            value,
        )

    head_columns = list(value.columns[:_AUDIT_EDGE_SAMPLE_COLUMNS])
    tail_columns = list(value.columns[-_AUDIT_EDGE_SAMPLE_COLUMNS:])
    sampled_columns = list(dict.fromkeys([*head_columns, *tail_columns]))
    return (
        {
            "count": int(len(value.columns)),
            "sampled": [_audit_value(column, key_labels=key_labels) for column in sampled_columns],
            "sample_truncated": True,
        },
        value.loc[:, sampled_columns],
    )


def _audit_frame_sample(
    value: "pd.DataFrame",
    *,
    key_labels: Mapping[str, str] | None = None,
    rows: int = _AUDIT_EDGE_SAMPLE_ROWS,
) -> dict[str, Any]:
    columns = [_audit_value(column, key_labels=key_labels) for column in value.columns.tolist()]

    def _slice_payload(sample: "pd.DataFrame") -> dict[str, Any]:
        return {
            "columns": columns,
            "index": [_audit_value(item, key_labels=key_labels) for item in sample.index.tolist()],
            "rows": _audit_frame_rows(sample, key_labels=key_labels),
        }

    if len(value) <= rows * 2:
        return {"head": _slice_payload(value)}
    return {
        "head": _slice_payload(value.head(rows)),
        "tail": _slice_payload(value.tail(rows)),
    }


def _audit_sequence_sample(
    values: list[Any],
    *,
    key_labels: Mapping[str, str] | None = None,
    seen: set[int] | None = None,
    items: int = _AUDIT_EDGE_SAMPLE_ITEMS,
) -> dict[str, Any]:
    if len(values) <= items * 2:
        return {"head": [_audit_value(item, key_labels=key_labels, _seen=seen) for item in values]}
    return {
        "head": [_audit_value(item, key_labels=key_labels, _seen=seen) for item in values[:items]],
        "tail": [_audit_value(item, key_labels=key_labels, _seen=seen) for item in values[-items:]],
    }


def _audit_contract_metadata_value(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        return _audit_value(value)
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            rows.append({
                "product": "",
                "contract": _audit_value(item),
                "start": "",
                "end": "",
            })
            continue
        rows.append({
            "product": _audit_value(item.get("product") or ""),
            "contract": _audit_value(item.get("contract") or item.get("contract_product") or item.get("uid") or ""),
            "start": _audit_value(item.get("start") or ""),
            "end": _audit_value(item.get("end") or ""),
        })
    return {
        "type": "ContractMetadataTable",
        "columns": ["product", "contract", "start", "end"],
        "rows": rows,
    }


def _audit_price_tables_value(value: Any, *, key_labels: Mapping[str, str] | None = None) -> Any:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        return _audit_value(value, key_labels=key_labels)
    rows: list[dict[str, Any]] = []
    for basis in sorted(value.keys(), key=str):
        table = value[basis]
        if isinstance(table, pd.DataFrame):
            row_count, column_count = table.shape
            columns, sample_frame = _audit_frame_column_payload(table, key_labels=key_labels)
            rows.append({
                "basis": str(basis),
                "shape": [int(row_count), int(column_count)],
                "index": _audit_index_bounds(table.index, key_labels=key_labels),
                "columns": columns,
                "sample": _audit_frame_sample(sample_frame, key_labels=key_labels, rows=2),
            })
        else:
            rows.append({
                "basis": str(basis),
                "shape": None,
                "index": None,
                "columns": None,
                "value": _audit_value(table, key_labels=key_labels),
            })
    return {
        "type": "PriceTablesSummary",
        "columns": ["basis", "shape", "index", "columns"],
        "rows": rows,
    }


def _audit_field_value(ref: "FieldRef", value: Any, *, key_labels: Mapping[str, str] | None = None) -> Any:
    if ref.qualified_name == _CONTRACT_METADATA_FIELD:
        return _audit_contract_metadata_value(value)
    if ref.qualified_name == _PRICE_TABLES_FIELD:
        return _audit_price_tables_value(value, key_labels=key_labels)
    return _audit_value(value, key_labels=key_labels)


def _audit_value(
    value: Any,
    *,
    key_labels: Mapping[str, str] | None = None,
    _seen: set[int] | None = None,
) -> Any:
    """Convert a runtime value into SSE-safe audit data.

    The step protocol must not rely on a terminal's abbreviated ``repr``.
    Nested mappings/collections are recursively preserved. Large pandas values
    are intentionally summarized: raw market-data tables can span many rows and
    products, while step-mode audit only needs enough shape/range/sample
    evidence for a human to verify which data window was used.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if type(value).__module__.startswith("numpy") and hasattr(value, "item"):
        return _audit_value(value.item(), key_labels=key_labels, _seen=_seen)
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return str(value)
    from tools.data.types.data_money import DataMoney
    if isinstance(value, DataMoney):
        stored_amount = _audit_value(value.amount, key_labels=key_labels, _seen=_seen)
        major_amount = _audit_value(value.to_major(), key_labels=key_labels, _seen=_seen)
        return {
            "type": "DataMoney",
            "currency": value.currency,
            "use_minor_units": bool(value.use_minor_units),
            "scale": int(value.scale),
            "amount": stored_amount,
            "amount_unit": "minor" if value.use_minor_units else "major",
            "minor_units": stored_amount if value.use_minor_units else None,
            "major_units": major_amount,
            "display": str(value),
        }
    if isinstance(value, EventDraft):
        return _audit_event_draft_value(value, key_labels=key_labels)
    if type(value).__name__ == "TimestampTradingDayResolver":
        return _audit_trading_day_resolver_value(value, key_labels=key_labels)
    if isinstance(value, pd.Series):
        if len(value) > _AUDIT_MAX_FULL_SERIES_LENGTH:
            return {
                "type": "Series",
                "name": _audit_value(value.name, key_labels=key_labels),
                "length": int(len(value)),
                "index": _audit_index_bounds(value.index, key_labels=key_labels),
                "sample": _audit_series_sample(value, key_labels=key_labels),
                "truncated": True,
            }
        return {
            "type": "Series",
            "name": _audit_value(value.name, key_labels=key_labels),
            "index": [_audit_value(item, key_labels=key_labels) for item in value.index.tolist()],
            "values": [_audit_value(item, key_labels=key_labels) for item in value.tolist()],
        }
    if isinstance(value, pd.DataFrame):
        rows, columns = value.shape
        if rows > _AUDIT_MAX_FULL_FRAME_ROWS or rows * columns > _AUDIT_MAX_FULL_FRAME_CELLS:
            column_payload, sample_frame = _audit_frame_column_payload(value, key_labels=key_labels)
            return {
                "type": "DataFrame",
                "shape": [int(rows), int(columns)],
                "columns": column_payload,
                "index": _audit_index_bounds(value.index, key_labels=key_labels),
                "sample": _audit_frame_sample(sample_frame, key_labels=key_labels),
                "truncated": True,
            }
        return {
            "type": "DataFrame",
            "columns": [_audit_value(column, key_labels=key_labels) for column in value.columns.tolist()],
            "index": [_audit_value(item, key_labels=key_labels) for item in value.index.tolist()],
            "rows": _audit_frame_rows(value, key_labels=key_labels),
        }

    seen = _seen if _seen is not None else set()
    object_id = id(value)
    if object_id in seen:
        return {"type": type(value).__name__, "cycle": True}
    seen.add(object_id)
    try:
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Mapping):
            return {
                key_labels.get(str(key), str(key)) if key_labels is not None else str(key): _audit_value(
                    item, key_labels=key_labels, _seen=seen,
                )
                for key, item in value.items()
            }
        from tools.data.types import UniqueNameObject
        if isinstance(value, (list, tuple, set, frozenset)):
            if value and isinstance(next(iter(value)), UniqueNameObject):
                return str(sorted(value, key=str))
            values = list(value)
            if len(values) > _AUDIT_MAX_FULL_MAPPING_SEQUENCE_ITEMS and all(isinstance(item, Mapping) for item in values):
                return {
                    "type": type(value).__name__,
                    "length": int(len(values)),
                    "sample": _audit_sequence_sample(values, key_labels=key_labels, seen=seen),
                    "truncated": True,
                }
            if len(values) > _AUDIT_MAX_FULL_SEQUENCE_ITEMS:
                return {
                    "type": type(value).__name__,
                    "length": int(len(values)),
                    "sample": _audit_sequence_sample(values, key_labels=key_labels, seen=seen),
                    "truncated": True,
                }
            return [_audit_value(item, key_labels=key_labels, _seen=seen) for item in values]
        if isinstance(value, UniqueNameObject):
            return str(value)
        if type(value).__name__ in {"TargetWeightIntent", "OrderDeltaIntent"}:
            return _audit_trade_intent_value(value, key_labels=key_labels, seen=seen)
        to_audit_dict = getattr(value, "to_audit_dict", None)
        if callable(to_audit_dict):
            return _audit_value(to_audit_dict(), key_labels=key_labels, _seen=seen)
        to_selection = getattr(value, "to_product_path_selection_dict", None)
        if callable(to_selection):
            return _audit_value(to_selection(), key_labels=key_labels, _seen=seen)
        if is_dataclass(value) and not isinstance(value, type):
            # ``dataclasses.asdict`` deep-copies every nested member. Runtime
            # product views deliberately cannot be reconstructed by deepcopy,
            # so traverse declared fields without mutating or copying them.
            try:
                declared_fields = dataclass_fields(value)
            except (AttributeError, TypeError):
                # Some dynamic/runtime objects expose a non-dataclass
                # ``__dataclass_fields__`` marker.  ``is_dataclass`` accepts
                # those, while ``fields`` correctly rejects them.
                declared_fields = ()
            if declared_fields:
                return {
                    field.name: _audit_value(getattr(value, field.name), key_labels=key_labels, _seen=seen)
                    for field in declared_fields
                }
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            try:
                return _audit_value(to_dict(), key_labels=key_labels, _seen=seen)
            except (TypeError, ValueError):
                pass
        return {"type": type(value).__name__, "repr": str(value)}
    finally:
        seen.discard(object_id)


def _audit_event_draft_value(value: EventDraft, *, key_labels: Mapping[str, str] | None = None) -> dict[str, Any]:
    strategy = getattr(value, "strategy", None)
    ledger = getattr(value, "ledger", None)
    return {
        "type": "EventDraft",
        "kind": value.kind.name.lower(),
        "timestamp": _audit_value(value.timestamp, key_labels=key_labels),
        "sequence": value.sequence,
        "strategy": key_labels.get(str(strategy), str(strategy)) if strategy is not None and key_labels is not None else (str(strategy) if strategy is not None else ""),
        "ledger": str(ledger) if ledger is not None else "",
        "payload": _audit_value(value.payload, key_labels=key_labels),
        "index_key": _audit_value(value.index_key, key_labels=key_labels),
    }


def _audit_trade_intent_value(value: Any, *, key_labels: Mapping[str, str] | None, seen: set[int]) -> dict[str, Any]:
    if hasattr(value, "weights"):
        return {
            "type": "TargetWeightIntent",
            "reason": _audit_value(getattr(value, "reason", ""), key_labels=key_labels, _seen=seen),
            "weights": _audit_value(getattr(value, "weights", {}), key_labels=key_labels, _seen=seen),
        }
    if hasattr(value, "deltas"):
        return {
            "type": "OrderDeltaIntent",
            "reason": _audit_value(getattr(value, "reason", ""), key_labels=key_labels, _seen=seen),
            "deltas": _audit_value(getattr(value, "deltas", {}), key_labels=key_labels, _seen=seen),
        }
    return {"type": type(value).__name__, "repr": str(value)}


def _audit_trading_day_resolver_value(value: Any, *, key_labels: Mapping[str, str] | None = None) -> dict[str, Any]:
    series = getattr(value, "_series", None)
    if not isinstance(series, pd.Series):
        return {"type": type(value).__name__, "repr": str(value)}
    clean = series.dropna().sort_index()
    trading_days = pd.DatetimeIndex(pd.to_datetime(clean.to_numpy(), errors="coerce")).dropna().unique()
    trading_days = pd.DatetimeIndex(trading_days).sort_values()
    sample = pd.DataFrame({
        "trading_day": [str(pd.Timestamp(item).normalize().date()) for item in clean.to_list()],
    }, index=clean.index)
    return {
        "type": "TimestampTradingDayResolver",
        "purpose": "timestamp -> trading_day for trading-day-scoped historical field rows",
        "effective_rule": (
            "rows with effective_timestamp are compared against the actual timestamp; "
            "only rows without effective_timestamp use the mapped trading_day"
        ),
        "mapping_count": int(len(clean)),
        "timestamp_index": _audit_index_bounds(clean.index, key_labels=key_labels),
        "trading_days": {
            "count": int(len(trading_days)),
            "start": str(trading_days[0].date()) if len(trading_days) else None,
            "end": str(trading_days[-1].date()) if len(trading_days) else None,
        },
        "sample": _audit_frame_sample(sample, key_labels=key_labels, rows=3),
    }


import pandas as pd

from .events import EventDraft, EventKind
from .flow import Flow, FlowBinding, Phase, phase_label

if TYPE_CHECKING:
    from .ledger import Ledger
    from .profiling import BacktestProfiler
    from .state import BacktestRunState
    from .strategy import Strategy
    from tools.testers.backtest.modules.base import FieldRef


class SchedulerError(Exception):
    pass


class ProgressSink(Protocol):
    def wants_live_event(self, event: str) -> bool: ...
    def emit_activity_manifest(self, phases: list[dict[str, Any]]) -> None: ...
    def emit_activity(self, **payload: Any) -> None: ...
    def emit_signal_progress(
        self,
        *,
        completed: int,
        total: int,
        phase: str = "event_replay",
        percent: float | None = None,
    ) -> None: ...


# ── FlowRegistry ──────────────────────────────────────────────────


@dataclass(frozen=True)
class ResolvedFlow:
    name: str
    owner: str
    inputs: tuple["FieldRef", ...]
    outputs: tuple["FieldRef", ...]
    phase: Phase
    event_kind: EventKind | None
    order: int
    after: tuple[Any, ...]
    before: tuple[Any, ...]
    compute: Callable[..., None]
    description: str = ""
    strategy_scoped: bool = False
    definition_name: str = ""
    input_materialization: bool = False
    event_payload_inputs: tuple[str, ...] = ()

    @property
    def effective_description(self) -> str:
        return self.description or self.name

    @property
    def activity_key(self) -> str:
        event = self.event_kind.name.lower() if self.event_kind is not None else "once"
        return f"{self.phase.value}.{event}.{self.name}"


def _flow_qualified_name(flow: ResolvedFlow) -> str:
    return f"{flow.owner}.{flow.name}" if getattr(flow, "owner", "") else f".{flow.name}"


class FlowRegistry:
    """Keyed by (name, phase, event_kind), not name alone -- a logical
    Flow "name" can legitimately be registered twice under the SAME name
    if the two registrations live in different (phase, event_kind) groups
    (e.g. FactorSignalModule's "signal_precomputed": one PRE_REPLAY Flow
    that schedules timestamps, one PER_EVENT Flow that looks up the value,
    both gated by the same StrategyConfig.active_flow_names entry by
    design). Duplicate (name, phase, event_kind) is still rejected --
    that's a real conflict, not an intentional phase-split."""

    def __init__(self) -> None:
        self._flows: dict[tuple[str, Phase, EventKind | None], Flow | FlowBinding] = {}

    def register_flow(self, flow: Flow | FlowBinding) -> None:
        key = (_flow_name(flow), flow.phase, flow.event_kind)
        if key in self._flows:
            raise ValueError(f"duplicate flow registration: {key}")
        self._flows[key] = flow

    def resolve(self) -> list[ResolvedFlow]:
        resolved: list[ResolvedFlow] = []
        for (name, _phase, _event_kind), base in self._flows.items():
            compute = base.compute
            inputs = set(base.inputs)
            resolved.append(ResolvedFlow(
                name=name, definition_name=_flow_definition_name(base),
                owner=base.owner, inputs=tuple(inputs), outputs=base.outputs,
                phase=base.phase, event_kind=base.event_kind, order=base.order,
                after=base.after, before=base.before, compute=compute,
                description=base.effective_description, strategy_scoped=_flow_strategy_scoped(base),
                input_materialization=_flow_input_materialization(base),
                event_payload_inputs=_flow_event_payload_inputs(base),
            ))
        return resolved


def _flow_name(flow: Flow | FlowBinding) -> str:
    if isinstance(flow, FlowBinding):
        return flow.effective_name
    return flow.name


def _flow_definition_name(flow: Flow | FlowBinding) -> str:
    return flow.definition_name


def _flow_strategy_scoped(flow: Flow | FlowBinding) -> bool:
    if isinstance(flow, FlowBinding):
        return flow.effective_strategy_scoped
    return flow.strategy_scoped


def _flow_input_materialization(flow: Flow | FlowBinding) -> bool:
    if isinstance(flow, FlowBinding):
        return flow.effective_input_materialization
    return flow.input_materialization


def _flow_event_payload_inputs(flow: Flow | FlowBinding) -> tuple[str, ...]:
    if isinstance(flow, FlowBinding):
        return flow.effective_event_payload_inputs
    return flow.event_payload_inputs


# ── sort_and_validate ─────────────────────────────────────────────


def _group_key(f: ResolvedFlow) -> tuple[Phase, EventKind | None]:
    return (f.phase, f.event_kind)


def sort_and_validate(
    flows: list[ResolvedFlow],
) -> dict[tuple[Phase, EventKind | None], list[ResolvedFlow]]:
    groups: dict[tuple[Phase, EventKind | None], list[ResolvedFlow]] = defaultdict(list)
    for f in flows:
        if f.phase is Phase.PER_EVENT and f.event_kind is None:
            raise SchedulerError(f"flow {f.name!r} phase=PER_EVENT must declare event_kind")
        if f.phase is not Phase.PER_EVENT and f.event_kind is not None:
            raise SchedulerError(f"flow {f.name!r} phase={f.phase} must not declare event_kind")
        groups[_group_key(f)].append(f)

    result: dict[tuple[Phase, EventKind | None], list[ResolvedFlow]] = {}
    for key, group in groups.items():
        result[key] = _sort_and_validate_group(group)
    return result


def _sort_and_validate_group(flows: list[ResolvedFlow]) -> list[ResolvedFlow]:
    ordered = sorted(flows, key=lambda f: (f.order, f.name))
    position = {f.name: i for i, f in enumerate(ordered)}
    producers_of: dict["FieldRef", list[str]] = defaultdict(list)
    for f in ordered:
        for out in f.outputs:
            producers_of[out].append(f.name)

    for f in ordered:
        for inp in f.inputs:
            producers = producers_of.get(inp, [])
            prior_or_current = [
                producer
                for producer in producers
                if position[producer] <= position[f.name]
            ]
            if producers and not prior_or_current:
                future_producers = ", ".join(repr(producer) for producer in producers)
                raise SchedulerError(
                    f"flow {f.name!r} depends on {inp.qualified_name!r}, "
                    f"but all producer flows ({future_producers}) are ordered after it")
        for dep in f.after:
            if dep.name in position and position[dep.name] > position[f.name]:
                raise SchedulerError(f"flow {f.name!r} must be ordered after {dep.qualified_name!r}")
        for dep in f.before:
            if dep.name in position and position[dep.name] < position[f.name]:
                raise SchedulerError(f"flow {f.name!r} must be ordered before {dep.qualified_name!r}")
    return ordered


# ── FlowContext ───────────────────────────────────────────────────


class FlowContext:
    """Per-dispatch-batch scratch. `get`/`set` are unkeyed (PRE_REPLAY/
    POST_REPLAY, no "active strategies" concept); `get_for`/`set_for` are
    keyed by (FieldRef, Strategy) for PER_EVENT batches with multiple
    active strategies. Setting an EventDraft (or list of them) pushes it
    into the event queue immediately — no buffering, no separate flush."""

    def __init__(
        self,
        timestamp: pd.Timestamp | None,
        event_queue: "EventQueue",
        active_strategies: frozenset["Strategy"] = frozenset(),
        active_ledgers: frozenset["Ledger"] = frozenset(),
        drafts_by_strategy: dict["Strategy", list[EventDraft]] | None = None,
        drafts_by_ledger: dict["Ledger", list[EventDraft]] | None = None,
        audit_contract: bool = False,
        enforce_contract: bool = False,
        event_kind: EventKind | None = None,
    ) -> None:
        self.timestamp = timestamp
        self.event_kind = event_kind
        self.active_strategies = active_strategies
        self.active_ledgers = active_ledgers
        # A strategy can have multiple simultaneous drafts in one dispatch
        # batch (e.g. several ORDER events for different products firing at
        # the same timestamp) -- always a list, never collapsed to one.
        self._drafts_by_strategy: dict["Strategy", list[EventDraft]] = drafts_by_strategy or {}
        self._drafts_by_ledger: dict["Ledger", list[EventDraft]] = drafts_by_ledger or {}
        self._payloads_by_strategy_cache: dict["Strategy", list[Any]] = {}
        # Keep the unwrapped/filter result per event kind as an immutable
        # tuple.  ``payloads_for`` still returns a fresh list, preserving the
        # historical container-mutation semantics while avoiding repeated
        # list construction in the many ORDER-stage flows.
        self._payloads_by_strategy_kind_cache: dict[
            "Strategy", dict[str | None, tuple[Any, ...]]
        ] = {}
        self._payloads_by_ledger_cache: dict["Ledger", list[Any]] = {}
        self._event_queue = event_queue
        self._values: dict["FieldRef", Any] = {}
        self._values_by_strategy: dict["FieldRef", dict["Strategy", Any]] = {}
        self._audit_contract = audit_contract
        self._enforce_contract = enforce_contract
        self._active_flow: ResolvedFlow | None = None
        self._contract_audit_token = object()
        self._contract_violations: list[dict[str, Any]] = []
        self._warned_contract_violations: set[tuple[str, str, str]] = set()

    def get(self, ref: "FieldRef", default: Any = None) -> Any:
        if self._audit_contract or self._enforce_contract:
            self._record_contract_access("read", ref)
        return self._values.get(ref, default)

    def set(self, ref: "FieldRef", value: Any) -> None:
        if self._audit_contract or self._enforce_contract:
            self._record_contract_access("write", ref)
        self._values[ref] = value
        self._push_if_event(value)

    def get_for(self, ref: "FieldRef", strategy: "Strategy", default: Any = None) -> Any:
        if self._audit_contract or self._enforce_contract:
            self._record_contract_access("read", ref)
        return self._values_by_strategy.get(ref, {}).get(strategy, default)

    def set_for(self, ref: "FieldRef", strategy: "Strategy", value: Any) -> None:
        if self._audit_contract or self._enforce_contract:
            self._record_contract_access("write", ref)
        self._values_by_strategy.setdefault(ref, {})[strategy] = value
        self._push_if_event(value, strategy)

    def enter_flow(self, flow: ResolvedFlow) -> None:
        self._active_flow = flow

    def exit_flow(self) -> None:
        self._active_flow = None

    def contract_violations(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._contract_violations)

    def contract_audit_token(self) -> object:
        return self._contract_audit_token

    def record_external_contract_read(self, ref: "FieldRef", token: object) -> None:
        if token is not self._contract_audit_token:
            raise SchedulerError("invalid flow-contract audit token")
        self._record_contract_access("read", ref)

    def record_external_contract_write(self, ref: "FieldRef", token: object) -> None:
        if token is not self._contract_audit_token:
            raise SchedulerError("invalid flow-contract audit token")
        self._record_contract_access("write", ref)

    def _record_contract_access(self, access: str, ref: "FieldRef") -> None:
        if not self._audit_contract and not self._enforce_contract:
            return
        flow = self._active_flow
        if flow is None:
            return
        declared = flow.inputs if access == "read" else flow.outputs
        if ref in declared:
            return
        violation = {
            "flow": _flow_qualified_name(flow),
            "phase": flow.phase.value,
            "event_kind": flow.event_kind.name if flow.event_kind is not None else "",
            "access": access,
            "field": ref.qualified_name,
        }
        self._contract_violations.append(violation)
        if self._enforce_contract:
            raise SchedulerError(
                f"flow {_flow_qualified_name(flow)!r} performed undeclared {access} "
                f"of field {ref.qualified_name!r}"
            )
        warn_key = (_flow_qualified_name(flow), access, ref.qualified_name)
        if warn_key not in self._warned_contract_violations:
            self._warned_contract_violations.add(warn_key)
            warnings.warn(
                f"flow {_flow_qualified_name(flow)!r} performed undeclared {access} "
                f"of field {ref.qualified_name!r}",
                RuntimeWarning,
                stacklevel=3,
            )

    def _record_event_payload_read(self, payloads: list[Any]) -> None:
        if not self._audit_contract and not self._enforce_contract:
            return
        flow = self._active_flow
        if flow is None:
            return
        kinds = sorted({self._event_payload_kind(payload) for payload in payloads})
        declared = {str(item) for item in flow.event_payload_inputs}
        if "*" in declared or set(kinds) <= declared:
            return
        for kind in (item for item in kinds if item not in declared):
            field = f"event_payload:{kind}"
            violation = {
                "flow": _flow_qualified_name(flow),
                "phase": flow.phase.value,
                "event_kind": flow.event_kind.name if flow.event_kind is not None else "",
                "access": "read",
                "field": field,
            }
            self._contract_violations.append(violation)
            if self._enforce_contract:
                raise SchedulerError(
                    f"flow {_flow_qualified_name(flow)!r} performed undeclared read "
                    f"of event payload kind {kind!r}"
                )
            warn_key = (_flow_qualified_name(flow), "read", field)
            if warn_key not in self._warned_contract_violations:
                self._warned_contract_violations.add(warn_key)
                warnings.warn(
                    f"flow {_flow_qualified_name(flow)!r} performed undeclared read "
                    f"of event payload kind {kind!r}",
                    RuntimeWarning,
                    stacklevel=3,
                )

    def _event_payload_kind(self, payload: Any) -> str:
        if isinstance(payload, Mapping):
            kind = payload.get("kind")
            if kind not in (None, ""):
                return str(kind)
        if self.event_kind is not None:
            return self.event_kind.name.lower()
        return "unknown"

    def _push_if_event(self, value: Any, strategy: "Strategy | None" = None) -> None:
        if isinstance(value, (TimerSchedule, TimerCancel)):
            if strategy is None:
                raise SchedulerError("timer control requires a strategy-scoped output")
            self._event_queue.apply_timer_control(strategy, value)
            return
        if isinstance(value, EventDraft):
            self._event_queue.push_event(value)
        elif isinstance(value, list) and value and isinstance(value[0], EventDraft):
            push_events = getattr(self._event_queue, "push_events", None)
            if callable(push_events):
                push_events(value)
            else:
                for draft in value:
                    self._event_queue.push_event(draft)

    def payload_for(self, strategy: "Strategy") -> Any:
        """For event kinds that only ever carry one draft per strategy per
        batch (SIGNAL). Raises if this strategy actually has more than one
        draft in this batch -- that's an ORDER-kind situation and the
        caller should use `payloads_for` instead, not silently pick one."""
        drafts = self._drafts_by_strategy[strategy]
        if len(drafts) != 1:
            raise SchedulerError(
                f"payload_for expected exactly one draft for {strategy!r} in this "
                f"batch, found {len(drafts)} -- use payloads_for for event kinds "
                "that can carry multiple simultaneous drafts per strategy (e.g. ORDER)")
        payload = _unwrap_order_attempt(drafts[0].payload)
        self._record_event_payload_read([payload])
        return payload

    def payloads_for(self, strategy: "Strategy", *, kind: str | None = None) -> list[Any]:
        """All payloads for this strategy in this dispatch batch, in the
        order they were popped off the EventQueue (stable for equal
        timestamp+kind, see EventQueue's counter tiebreak). A strategy can
        have several simultaneous ORDER events at one timestamp (one per
        product being rebalanced) -- all of them must be processed, not
        just the last one."""
        by_kind = self._payloads_by_strategy_kind_cache.get(strategy)
        if by_kind is None:
            by_kind = {}
            self._payloads_by_strategy_kind_cache[strategy] = by_kind
        cached = by_kind.get(kind)
        if cached is None:
            raw_payloads = self._payloads_by_strategy_cache.get(strategy)
            if raw_payloads is None:
                raw_payloads = [
                    draft.payload
                    for draft in self._drafts_by_strategy.get(strategy, ())
                ]
                self._payloads_by_strategy_cache[strategy] = raw_payloads
            cached = tuple(
                _unwrap_order_attempt(payload)
                for payload in self._filter_event_payloads(raw_payloads, kind=kind)
            )
            by_kind[kind] = cached
        payloads = list(cached)
        self._record_event_payload_read(payloads)
        return payloads

    def payloads_for_ledger(self, ledger: "Ledger", *, kind: str | None = None) -> list[Any]:
        """All payloads for this ledger in this dispatch batch.

        Ledger-scoped events intentionally do not require a strategy carrier.
        Strategy routing remains available separately only to gate which flows
        are active for the strategies attached to this ledger.
        """
        from .ledger import ledger_identity

        ledger_key = ledger_identity(ledger)
        cached = self._payloads_by_ledger_cache.get(ledger_key)
        if cached is None:
            cached = [draft.payload for draft in self._drafts_by_ledger.get(ledger_key, ())]
            self._payloads_by_ledger_cache[ledger_key] = cached
        payloads = self._filter_event_payloads(cached, kind=kind)
        self._record_event_payload_read(payloads)
        return payloads

    def _filter_event_payloads(self, payloads: list[Any], *, kind: str | None) -> list[Any]:
        if kind is None:
            return payloads
        return [payload for payload in payloads if self._event_payload_kind(payload) == kind]

    def draft_for(self, strategy: "Strategy") -> EventDraft:
        drafts = self._drafts_by_strategy[strategy]
        if len(drafts) != 1:
            raise SchedulerError(
                f"draft_for expected exactly one draft for {strategy!r} in this "
                f"batch, found {len(drafts)}")
        return drafts[0]


# ── EventQueue ────────────────────────────────────────────────────


class EventQueue:
    """Single global priority queue keyed (timestamp, kind, sequence, counter).
    `kind` (an IntEnum) participates directly in sort ordering — no-
    lookahead is guaranteed structurally by causal_valuation's precomputed
    ffill-only series, not by queue mechanics, so there's no separate
    "bucket"/"tick" concept here."""

    def __init__(self) -> None:
        self._heap: list[tuple[pd.Timestamp, EventKind, int, int, EventDraft]] = []
        self._counter = itertools.count()
        self._dispatchers: dict[EventKind, Callable[[list[EventDraft]], None]] = {}
        self._timer_generations = itertools.count(1)
        self._timers: dict[tuple[Any, str], tuple[int, Any]] = {}

    def apply_timer_control(self, strategy: "Strategy", control: Any) -> None:
        """Apply a strategy timer request without exposing queue internals."""
        key = (strategy, getattr(control, "name", ""))
        if isinstance(control, TimerCancel):
            self._timers.pop(key, None)
            return
        if not isinstance(control, TimerSchedule):
            raise TypeError(f"unsupported timer control: {type(control).__name__}")
        generation = next(self._timer_generations)
        self._timers[key] = (generation, control)
        self.push_event(EventDraft(
            EventKind.TIMER,
            control.first_timestamp,
            strategy,
            payload=TimerEvent(control.name, control.first_timestamp, generation=generation),
        ))

    def _timer_event_active(self, draft: EventDraft) -> bool:
        from .timer_events import TimerEvent

        event = draft.payload
        if not isinstance(event, TimerEvent):
            return True
        registration = self._timers.get((draft.strategy, event.name))
        return registration is not None and registration[0] == event.generation

    def _advance_timer(self, draft: EventDraft) -> None:
        from .timer_events import TimerEvent

        event = draft.payload
        if not isinstance(event, TimerEvent):
            return
        registration = self._timers.get((draft.strategy, event.name))
        if registration is None or registration[0] != event.generation:
            return
        generation, schedule = registration
        if schedule.interval is None:
            self._timers.pop((draft.strategy, event.name), None)
            return
        next_timestamp = event.timestamp + schedule.interval
        if schedule.end_timestamp is not None and next_timestamp > schedule.end_timestamp:
            self._timers.pop((draft.strategy, event.name), None)
            return
        self.push_event(EventDraft(
            EventKind.TIMER,
            next_timestamp,
            draft.strategy,
            payload=TimerEvent(
                event.name,
                next_timestamp,
                occurrence=event.occurrence + 1,
                generation=generation,
            ),
        ))

    def set_dispatcher(self, kind: EventKind, dispatcher: Callable[[list[EventDraft]], None]) -> None:
        self._dispatchers[kind] = dispatcher

    def push_event(self, draft: EventDraft) -> None:
        heapq.heappush(self._heap, (draft.timestamp, draft.kind, draft.sequence, next(self._counter), draft))

    def push_events(self, drafts: list[EventDraft]) -> None:
        if not drafts:
            return
        if len(drafts) < 64 or len(drafts) * 4 < len(self._heap):
            for draft in drafts:
                heapq.heappush(self._heap, (draft.timestamp, draft.kind, draft.sequence, next(self._counter), draft))
            return
        self._heap.extend((draft.timestamp, draft.kind, draft.sequence, next(self._counter), draft) for draft in drafts)
        heapq.heapify(self._heap)

    def pending_count(self) -> int:
        """O(1) -- `len()` on a list, not a heap walk."""
        return len(self._heap)

    def pending_count_by_kind(self, kind: EventKind) -> int:
        return sum(1 for _, draft_kind, _, _, _ in self._heap if draft_kind is kind)

    def snapshot_head(self, limit: int = 50) -> list[EventDraft]:
        """Return the next pending events in dispatch order without mutating the heap."""
        if limit <= 0:
            return []
        # ``snapshot_head`` is used by step-mode diagnostics, often once per
        # flow.  Sorting the complete pending heap made the diagnostic path
        # O(Q log Q) even though the UI only displays K entries.  nsmallest
        # keeps the same tuple ordering while reducing this to O(Q log K),
        # without mutating the event heap.
        return [
            draft
            for _timestamp, _kind, _sequence, _counter, draft in heapq.nsmallest(
                limit, self._heap,
            )
        ]

    def run_until_drained(self) -> None:
        """Progress reporting lives in `make_dispatcher` (Flow-level), not
        here -- a batch can fan out across many strategies x Flows, and
        that inner loop is where real work (and real wall-clock time) is
        spent, not the batching loop itself."""
        while self._heap:
            first_ts, first_kind, _, _, first = heapq.heappop(self._heap)
            batch = [first]
            while (
                self._heap
                and self._heap[0][0] == first_ts
                and self._heap[0][1] == first_kind
            ):
                batch.append(heapq.heappop(self._heap)[4])
            if first.kind is EventKind.TIMER:
                batch = [draft for draft in batch if self._timer_event_active(draft)]
                if not batch:
                    continue
            dispatcher = self._dispatchers.get(first.kind)
            if dispatcher is not None:
                dispatcher(batch)
            if first.kind is EventKind.TIMER:
                for draft in batch:
                    self._advance_timer(draft)


class _ProgressTracker:
    """Backtest activity reporter.

    The UI progress bar is keyed to initial SIGNAL event completion. Flow
    activity is a parallel stream used for text rotation and process display;
    it deliberately does not expose completed/total flow counts.
    """

    def __init__(
        self,
        state: "BacktestRunState",
        callback: Callable[[int, int, str], None] | None,
        activity_sink: ProgressSink | None,
        event_queue: EventQueue,
        flow_strategies: dict[str, frozenset["Strategy"]] | None = None,
    ) -> None:
        self._state = state
        self._callback = callback
        self._activity_sink = activity_sink
        self._event_queue = event_queue
        self._flow_strategies = flow_strategies or {}
        self._completed = 0
        self._signal_total = 0
        self._signal_completed = 0
        self._pre_total = 0
        self._pre_completed = 0
        self._post_total = 0
        self._post_completed = 0
        self._mode_info_cache: dict[
            tuple[int, frozenset["Strategy"]], dict[str, Any]
        ] = {}

    def emit_manifest(
        self,
        groups: dict[tuple[Phase, EventKind | None], list[ResolvedFlow]],
        state: "BacktestRunState",
        flow_strategies: dict[str, frozenset["Strategy"]],
    ) -> None:
        if self._activity_sink is not None:
            self._activity_sink.emit_activity_manifest(activity_manifest_from_groups(groups, state, flow_strategies))

    def set_phase_totals(self, *, pre_total: int, post_total: int) -> None:
        self._pre_total = max(0, pre_total)
        self._post_total = max(0, post_total)

    def note_signal_queue_ready(self) -> None:
        self._signal_total = self._event_queue.pending_count_by_kind(EventKind.SIGNAL)
        self._signal_completed = 0
        if self._activity_sink is not None:
            self._activity_sink.emit_signal_progress(
                completed=0,
                total=self._signal_total,
                phase="event_replay",
                percent=10.0,
            )

    def activity(
        self,
        flow: ResolvedFlow,
        *,
        timestamp: pd.Timestamp | None,
        phase: str | None = None,
        strategies: frozenset["Strategy"] | None = None,
    ) -> None:
        if self._activity_sink is None:
            return
        if flow.input_materialization:
            return
        wants_live_event = getattr(
            self._activity_sink, "wants_live_event", None,
        )
        if callable(wants_live_event) and not wants_live_event("activity"):
            return
        activity_phase = phase or _activity_phase_for_flow(flow)
        ts_text = timestamp.isoformat() if timestamp is not None else ""
        active_strategies = strategies or _strategies_using_flow(self._state, flow.name, self._flow_strategies)
        cache_key = (id(flow), active_strategies)
        mode_info = self._mode_info_cache.get(cache_key)
        if mode_info is None:
            mode_info = _mode_info_for_flow(
                self._state, flow, active_strategies,
            )
            self._mode_info_cache[cache_key] = mode_info
        self._activity_sink.emit_activity(
            phase=activity_phase,
            phase_label=phase_label(activity_phase),
            flow_key=flow.activity_key,
            flow_name=flow.name,
            flow_label=flow.effective_description,
            display_order=flow.order,
            event_kind=flow.event_kind.name if flow.event_kind is not None else "",
            timestamp=ts_text,
            timezone=str(getattr(getattr(timestamp, "tzinfo", None), "zone", "") or ""),
            message=_activity_message(ts_text, flow.effective_description),
            mode_info=mode_info,
        )

    def tick(self, label: str, *, phase: Phase) -> None:
        self._completed += 1
        if self._callback is not None:
            self._callback(self._completed, max(self._completed, 1), label)

    def signal_batch_done(self, batch_size: int) -> None:
        if batch_size <= 0:
            return
        self._signal_completed = min(self._signal_total, self._signal_completed + batch_size)
        if self._activity_sink is not None:
            ratio = 1.0 if self._signal_total <= 0 else self._signal_completed / self._signal_total
            self._activity_sink.emit_signal_progress(
                completed=self._signal_completed,
                total=self._signal_total,
                phase="event_replay",
                percent=10.0 + ratio * 80.0,
            )

    def phase_flow_done(self, *, phase: str) -> None:
        if self._activity_sink is None:
            return
        if phase == "pre_replay":
            self._pre_completed = min(self._pre_total, self._pre_completed + 1)
            ratio = 1.0 if self._pre_total <= 0 else self._pre_completed / self._pre_total
            self._activity_sink.emit_signal_progress(
                completed=self._pre_completed,
                total=self._pre_total,
                phase=phase,
                percent=ratio * 10.0,
            )
        elif phase == "post_replay":
            self._post_completed = min(self._post_total, self._post_completed + 1)
            ratio = 1.0 if self._post_total <= 0 else self._post_completed / self._post_total
            self._activity_sink.emit_signal_progress(
                completed=self._post_completed,
                total=self._post_total,
                phase=phase,
                percent=90.0 + ratio * 10.0,
            )

    def event_replay_done(self) -> None:
        if self._activity_sink is not None:
            self._activity_sink.emit_signal_progress(
                completed=self._signal_total,
                total=self._signal_total,
                phase="event_replay",
                percent=90.0,
            )

    def complete(self) -> None:
        if self._activity_sink is not None:
            self._activity_sink.emit_signal_progress(completed=1, total=1, phase="done", percent=100.0)


def _compute_with_optional_profiler(
    profiler: "BacktestProfiler | None",
    flow: ResolvedFlow,
    *,
    state: "BacktestRunState",
    ctx: FlowContext,
    timestamp: pd.Timestamp | None,
    strategies: frozenset["Strategy"] | None,
) -> None:
    if profiler is None:
        _compute_flow(flow, state, ctx)
        return
    token = profiler.begin_flow(flow)
    _compute_flow(flow, state, ctx)
    profiler.end_flow(
        token,
        flow,
        timestamp=timestamp,
        strategies=strategies,
    )



def _strategy_alias(state: "BacktestRunState", strategy: Any) -> str:
    from tools.testers.backtest.modules.strategy_book import strategy_book_store_for

    return strategy_book_store_for(state).display_name_for_strategy(strategy)


def _audit_ledgers(state: "BacktestRunState", strategies: frozenset["Strategy"], active_ledgers: frozenset[Any]) -> list[dict[str, Any]]:
    """Snapshot the complete ledger/cash-pool topology without mutating it."""
    from tools.testers.backtest.engines.native.ledger import ledger_identity
    from tools.testers.backtest.modules.strategy_book import cash_pool_id_for_ledger, strategy_book_store_for

    book = strategy_book_store_for(state)
    strategies_by_ledger: dict[Any, set[str]] = defaultdict(set)
    ledger_keys = {ledger_identity(ledger) for ledger in active_ledgers}
    for strategy in strategies:
        for ledger in book.ledgers_for_strategy(state, strategy):
            ledger_key = ledger_identity(ledger)
            ledger_keys.add(ledger_key)
            strategies_by_ledger[ledger_key].add(_strategy_alias(state, strategy))

    cash_store = getattr(state, "cash_pool_store", None)
    snapshots: list[dict[str, Any]] = []
    for ledger in sorted(ledger_keys, key=lambda item: item.name):
        ledger_state = state.ledgers.get(ledger)
        pool_id = str(cash_pool_id_for_ledger(state, ledger))
        field_values = {
            ref.qualified_name: _audit_value(value)
            for ref, value in (ledger_state.fields.items() if ledger_state is not None else ())
        }
        snapshots.append({
            "ledger": ledger.name,
            "strategies": sorted(strategies_by_ledger.get(ledger, set())),
            "cash_pool": pool_id,
            "cash": _audit_value(getattr(cash_store, "cash_by_ledger", {}).get(ledger.name)),
            "cash_pool_reserve": _audit_value(
                getattr(cash_store, "reserve_by_pool", {}).get(pool_id)
            ),
            "cash_pool_config": _audit_value(getattr(cash_store, "config_by_pool", {}).get(pool_id)),
            "ledger_config": _audit_value(state.ledger_configs.get(ledger)),
            "fields": field_values,
        })
    return snapshots


def _audit_field_values(
    state: "BacktestRunState",
    ctx: FlowContext,
    ref: "FieldRef",
    strategies: frozenset["Strategy"],
    ledger_snapshots: list[dict[str, Any]],
    *,
    include_strategy_config: bool,
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    strategy_key_labels = {str(strategy): _strategy_alias(state, strategy) for strategy in strategies}
    common = ctx._values.get(ref, _AUDIT_MISSING)
    if common is not _AUDIT_MISSING:
        values.append({"scope": "context", "value": _audit_field_value(ref, common, key_labels=strategy_key_labels)})
    for strategy in sorted(strategies, key=lambda item: _strategy_alias(state, item)):
        alias = _strategy_alias(state, strategy)
        config = state.config_for(strategy)
        if include_strategy_config and ref in config.field_values:
            values.append({
                "scope": "strategy_config",
                "strategy": alias,
                "value": _audit_field_value(ref, config.field_values[ref], key_labels=strategy_key_labels),
            })
        contextual = ctx._values_by_strategy.get(ref, {}).get(strategy, _AUDIT_MISSING)
        if contextual is not _AUDIT_MISSING:
            values.append({
                "scope": "strategy_context",
                "strategy": alias,
                "value": _audit_field_value(ref, contextual, key_labels=strategy_key_labels),
            })
    for ledger in ledger_snapshots:
        value = ledger["fields"].get(ref.qualified_name, _AUDIT_MISSING)
        if value is not _AUDIT_MISSING:
            values.append({
                "scope": "ledger",
                "ledger": ledger["ledger"],
                "cash_pool": ledger["cash_pool"],
                "strategies": ledger["strategies"],
                "value": value,
            })
        ledger_config = ledger.get("ledger_config") or {}
        if ref.name in ledger_config:
            values.append({
                "scope": "ledger_config",
                "ledger": ledger["ledger"],
                "cash_pool": ledger["cash_pool"],
                "strategies": ledger["strategies"],
                "value": ledger_config[ref.name],
            })
    return values


def _audit_field_records(
    state: "BacktestRunState",
    ctx: FlowContext,
    refs: tuple["FieldRef", ...],
    strategies: frozenset["Strategy"],
    ledger_snapshots: list[dict[str, Any]],
    *,
    include_strategy_config: bool,
) -> list[dict[str, Any]]:
    return [
        {
            "field": ref.qualified_name,
            "values": _audit_field_values(
                state,
                ctx,
                ref,
                strategies,
                ledger_snapshots,
                include_strategy_config=include_strategy_config,
            ),
        }
        for ref in refs
    ]


def _audit_strategy_context(state: "BacktestRunState", strategies: frozenset["Strategy"], ledger_snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ledgers_by_strategy: dict[str, list[str]] = defaultdict(list)
    for ledger in ledger_snapshots:
        for strategy in ledger["strategies"]:
            ledgers_by_strategy[strategy].append(ledger["ledger"])
    result: list[dict[str, Any]] = []
    for strategy in sorted(strategies, key=lambda item: _strategy_alias(state, item)):
        result.append({
            "strategy": _strategy_alias(state, strategy),
            "ledgers": sorted(ledgers_by_strategy.get(_strategy_alias(state, strategy), [])),
        })
    return result


def _audit_event_payloads(
    state: "BacktestRunState",
    ctx: FlowContext,
    strategies: frozenset["Strategy"],
    ledger_snapshots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for strategy in sorted(strategies, key=lambda item: _strategy_alias(state, item)):
        values = ctx.payloads_for(strategy) if strategy in ctx._drafts_by_strategy else []
        if values:
            payloads.append({"scope": "strategy", "strategy": _strategy_alias(state, strategy), "payloads": _audit_value(values)})
    for ledger in ledger_snapshots:
        from tools.testers.backtest.engines.native.ledger import ledger_identity

        ledger_key = ledger_identity(ledger["ledger"])
        values = ctx.payloads_for_ledger(ledger_key) if ledger_key in ctx._drafts_by_ledger else []
        if values:
            payloads.append({"scope": "ledger", "ledger": ledger["ledger"], "cash_pool": ledger["cash_pool"], "payloads": _audit_value(values)})
    return payloads


def _audit_current_event_batch(
    state: "BacktestRunState",
    ctx: FlowContext,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for strategy in sorted(ctx._drafts_by_strategy, key=lambda item: _strategy_alias(state, item)):
        for draft in ctx._drafts_by_strategy.get(strategy, ()):
            rows.append(_audit_event_subject_row(
                state,
                draft,
                strategy=_strategy_alias(state, strategy),
                ledger="",
            ))
    for ledger, drafts in sorted(ctx._drafts_by_ledger.items(), key=lambda item: str(item[0])):
        for draft in drafts:
            rows.append(_audit_event_subject_row(state, draft, strategy="", ledger=str(ledger)))
    return {
        "timestamp": str(ctx.timestamp) if ctx.timestamp is not None else "",
        "event_kind": ctx.event_kind.name if ctx.event_kind is not None else "",
        "batch_count": len(rows),
        "subjects": rows,
    }


def _audit_event_queue_head(state: "BacktestRunState", event_queue: EventQueue, *, limit: int = 50) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for index, draft in enumerate(event_queue.snapshot_head(limit), start=1):
        payload = _audit_event_subject_payload(draft.payload)
        rows.append({
            "index": index,
            "timestamp": str(draft.timestamp),
            "sequence": draft.sequence,
            "event_kind": draft.kind.name,
            "strategy": _strategy_alias(state, draft.strategy) if draft.strategy is not None else "",
            "ledger": str(draft.ledger) if draft.ledger is not None else "",
            "subject": _audit_value(
                payload.get("instrument")
                or payload.get("product")
                or payload.get("contract_product")
                or payload.get("contract")
                or payload.get("ledger_id")
                or draft.index_key
                or ""
            ),
            "action": _audit_value(
                payload.get("notice_type")
                or payload.get("kind")
                or payload.get("status")
                or payload.get("reason")
                or ""
            ),
            "order_id": _audit_value(payload.get("order_id") if isinstance(payload, dict) else ""),
        })
    return {
        "pending_count": event_queue.pending_count(),
        "head_count": len(rows),
        "head_limit": limit,
        "items": rows,
    }


def _audit_event_subject_row(
    state: "BacktestRunState",
    draft: EventDraft,
    *,
    strategy: str,
    ledger: str,
) -> dict[str, Any]:
    payload = _audit_event_subject_payload(draft.payload)
    subject = (
        payload.get("instrument")
        or payload.get("product")
        or payload.get("contract_product")
        or payload.get("contract")
        or payload.get("ledger_id")
        or _audit_value(draft.index_key)
        or ""
    )
    action = (
        payload.get("notice_type")
        or payload.get("kind")
        or payload.get("status")
        or payload.get("reason")
        or ""
    )
    return {
        "timestamp": str(draft.timestamp),
        "sequence": draft.sequence,
        "event_kind": draft.kind.name,
        "strategy": strategy,
        "ledger": ledger,
        "subject": _audit_value(subject),
        "action": _audit_value(action),
        "order_id": _audit_value(payload.get("order_id") if isinstance(payload, dict) else ""),
    }


def _audit_event_subject_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            result = to_dict()
            if isinstance(result, dict):
                return result
        except (TypeError, ValueError):
            pass
    result: dict[str, Any] = {}
    for key in ("instrument", "product", "contract_product", "contract", "ledger_id", "notice_type", "kind", "status", "reason", "order_id"):
        if hasattr(value, key):
            result[key] = getattr(value, key)
    fields = getattr(value, "fields", None)
    if isinstance(fields, dict):
        for key in ("instrument", "product", "contract_product", "contract", "ledger_id", "notice_type", "kind", "status", "reason", "order_id"):
            result.setdefault(key, fields.get(key))
    return result


def _audit_event_payload_changes(
    before: list[dict[str, Any]], after: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Diff mutable event payloads by their strategy/ledger routing scope."""
    def key(entry: dict[str, Any]) -> tuple[Any, ...]:
        return (
            entry.get("scope"), entry.get("strategy"), entry.get("ledger"),
            entry.get("cash_pool"),
        )

    before_by_key = {key(entry): entry.get("payloads") for entry in before}
    after_by_key = {key(entry): entry.get("payloads") for entry in after}
    changes: list[dict[str, Any]] = []
    for entry_key in sorted(set(before_by_key) | set(after_by_key), key=str):
        old = before_by_key.get(entry_key, _AUDIT_MISSING)
        new = after_by_key.get(entry_key, _AUDIT_MISSING)
        if old == new:
            continue
        scope, strategy, ledger, cash_pool = entry_key
        changes.append({
            "scope": scope,
            "strategy": strategy,
            "ledger": ledger,
            "cash_pool": cash_pool,
            "before": None if old is _AUDIT_MISSING else old,
            "after": None if new is _AUDIT_MISSING else new,
        })
    return changes


def _audit_record_changes(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(entry: dict[str, Any]) -> tuple[Any, ...]:
        return (
            entry.get("scope"), entry.get("strategy"), entry.get("ledger"),
            tuple(entry.get("strategies") or ()), entry.get("cash_pool"),
        )

    before_by_key = {key(entry): entry.get("value") for entry in before}
    after_by_key = {key(entry): entry.get("value") for entry in after}
    changes: list[dict[str, Any]] = []
    for entry_key in sorted(set(before_by_key) | set(after_by_key), key=str):
        old = before_by_key.get(entry_key, _AUDIT_MISSING)
        new = after_by_key.get(entry_key, _AUDIT_MISSING)
        if old != new:
            scope, strategy, ledger, strategies, cash_pool = entry_key
            changes.append({
                "scope": scope,
                "strategy": strategy,
                "ledger": ledger,
                "strategies": list(strategies),
                "cash_pool": cash_pool,
                "before": None if old is _AUDIT_MISSING else old,
                "after": None if new is _AUDIT_MISSING else new,
            })
    return changes


def _audit_position_book_change(change: dict[str, Any]) -> dict[str, Any]:
    """Replace whole-book before/after copies with lossless changed instruments."""
    before = change.get("before")
    after = change.get("after")
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        return change
    instruments = []
    for instrument in sorted(set(before) | set(after), key=str):
        old = before.get(instrument, _AUDIT_MISSING)
        new = after.get(instrument, _AUDIT_MISSING)
        if old == new:
            continue
        instruments.append({
            "instrument": str(instrument),
            "before": None if old is _AUDIT_MISSING else old,
            "after": None if new is _AUDIT_MISSING else new,
        })
    return {
        key: value for key, value in change.items()
        if key not in {"before", "after"}
    } | {
        "before_count": len(before),
        "after_count": len(after),
        "changes": instruments,
    }


def _audit_ledger_changes(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    before_by_ledger = {entry["ledger"]: entry for entry in before}
    after_by_ledger = {entry["ledger"]: entry for entry in after}
    changes: list[dict[str, Any]] = []
    for ledger_name in sorted(set(before_by_ledger) | set(after_by_ledger)):
        old = before_by_ledger.get(ledger_name, {})
        new = after_by_ledger.get(ledger_name, {})
        metadata = new or old
        if old.get("cash") != new.get("cash"):
            changes.append({
                "scope": "ledger",
                "ledger": ledger_name,
                "cash_pool": metadata.get("cash_pool"),
                "strategies": metadata.get("strategies", []),
                "field": "CashPoolModule.cash",
                "before": old.get("cash"),
                "after": new.get("cash"),
            })
        for field_name in sorted(set(old.get("fields", {})) | set(new.get("fields", {}))):
            old_value = old.get("fields", {}).get(field_name)
            new_value = new.get("fields", {}).get(field_name)
            if old_value != new_value:
                change = {
                    "scope": "ledger",
                    "ledger": ledger_name,
                    "cash_pool": metadata.get("cash_pool"),
                    "strategies": metadata.get("strategies", []),
                    "field": field_name,
                    "before": old_value,
                    "after": new_value,
                }
                changes.append(
                    _audit_position_book_change(change)
                    if field_name == "LedgerModule.positions"
                    else change
                )
    return changes


def _audit_ledger_topology(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep routing/cash identity; field values travel via inputs/changes."""
    return [
        {
            "ledger": item.get("ledger"),
            "strategies": list(item.get("strategies") or []),
            "cash_pool": item.get("cash_pool"),
            "cash": item.get("cash"),
        }
        for item in snapshots
    ]


def _audit_dmtm_step(
    flow: ResolvedFlow,
    before: dict[str, Any],
    ledger_changes: list[dict[str, Any]],
    outputs_after: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Project the generic step audit into a compact DMTM evidence block."""
    payload_entries = before.get("event_payloads", [])
    events: list[dict[str, Any]] = []
    for entry in payload_entries:
        for payload in entry.get("payloads", []):
            if not isinstance(payload, dict) or payload.get("kind") != "daily_mark_to_market":
                continue
            events.append({
                "ledger": str(payload.get("ledger_id") or entry.get("ledger") or ""),
                "trading_day": str(payload.get("trading_day") or ""),
            })
    if not events:
        return None

    inputs = before.get("inputs", [])
    accounting_field_names = {
        "TradingRuleModule.accounting_mode",
        "TradingRuleModule.daily_mark_to_market_enabled",
        "TradingRuleModule.cost_basis_method",
        "FeeModule.fee_mode",
        "MarginModule.margin_mode",
        "MarginModule.margin_call_mode",
    }
    market_rule_field_names = {
        "MarketDataModule.current_market_snapshot",
        "MarketDataModule.current_historical_fields",
    }
    return {
        "events": events,
        "resolved": next((
            item.get("values", []) for item in outputs_after
            if item.get("field") == "TradingRuleModule.resolved_daily_mark_to_market"
        ), []),
        "accounting_inputs": [
            item for item in inputs if item.get("field") in accounting_field_names
        ],
        "market_rule_inputs": [
            item for item in inputs if item.get("field") in market_rule_field_names
        ],
        "cash_changes": [
            item for item in ledger_changes if item.get("field") == "CashPoolModule.cash"
        ],
        "position_changes": [
            item for item in ledger_changes if str(item.get("field") or "").endswith(".positions")
        ],
        "margin_changes": [
            item for item in ledger_changes if "margin" in str(item.get("field") or "").lower()
        ],
    }


def _step_before_flow(f, state, ctx, timestamp, step_callback, applicable, all_active_ledgers):
    """Capture a complete pre-compute snapshot; emission happens after compute."""
    if not _step_mode_globals.get("enabled", False) or step_callback is None:
        return {}
    should_capture = getattr(step_callback, "should_capture", None)
    if callable(should_capture) and not should_capture(timestamp):
        return {}
    ledger_snapshots = _audit_ledgers(state, applicable, all_active_ledgers or ctx.active_ledgers)
    return {
        "timestamp": str(timestamp) if timestamp is not None else "",
        "current_event": _audit_current_event_batch(state, ctx),
        "inputs": _audit_field_records(
            state, ctx, f.inputs, applicable, ledger_snapshots, include_strategy_config=True,
        ),
        "outputs_before": _audit_field_records(
            state, ctx, f.outputs, applicable, ledger_snapshots, include_strategy_config=False,
        ),
        "ledgers_before": ledger_snapshots,
        "strategies": _audit_strategy_context(state, applicable, ledger_snapshots),
        "event_payloads": _audit_event_payloads(state, ctx, applicable, ledger_snapshots),
        "contract_violation_count": len(ctx.contract_violations()),
    }


def _step_after_flow(f, state, ctx, step_callback, before):
    """Emit one complete, post-compute audit event for a flow."""
    if not _step_mode_globals.get("enabled", False) or step_callback is None or not before:
        return
    strategies = ctx.active_strategies
    ledgers_after = _audit_ledgers(state, strategies, ctx.active_ledgers)
    outputs_after = _audit_field_records(
        state, ctx, f.outputs, strategies, ledgers_after, include_strategy_config=False,
    )
    outputs_before = {entry["field"]: entry["values"] for entry in before.get("outputs_before", [])}
    output_changes = []
    for output in outputs_after:
        for change in _audit_record_changes(outputs_before.get(output["field"], []), output["values"]):
            item = {"field": output["field"], **change}
            output_changes.append(
                _audit_position_book_change(item)
                if output["field"] == "LedgerModule.positions"
                else item
            )
    ledger_changes = _audit_ledger_changes(before.get("ledgers_before", []), ledgers_after)
    declared_outputs = {ref.qualified_name for ref in f.outputs}
    direct_contract_violations = list(ctx.contract_violations())[before.get("contract_violation_count", 0):]
    direct_violation_keys = {
        (
            item.get("flow"),
            item.get("phase"),
            item.get("event_kind"),
            item.get("access"),
            item.get("field"),
        )
        for item in direct_contract_violations
    }
    ledger_contract_violations = [
        {
            "flow": _flow_qualified_name(f),
            "phase": f.phase.value,
            "event_kind": f.event_kind.name if f.event_kind is not None else "",
            "access": "write",
            "field": change.get("field"),
        }
        for change in ledger_changes
        if change.get("field") not in declared_outputs
        and (
            _flow_qualified_name(f),
            f.phase.value,
            f.event_kind.name if f.event_kind is not None else "",
            "write",
            change.get("field"),
        ) not in direct_violation_keys
    ]
    if ledger_contract_violations and ctx._enforce_contract:
        first = ledger_contract_violations[0]
        raise SchedulerError(
            f"flow {_flow_qualified_name(f)!r} performed undeclared write "
            f"of field {first.get('field')!r}"
        )
    event_payloads_after = _audit_event_payloads(state, ctx, strategies, ledgers_after)
    event_payload_changes = _audit_event_payload_changes(
        before.get("event_payloads", []), event_payloads_after,
    )
    displayed_ledger_changes = [
        change for change in ledger_changes
        if change.get("field") not in declared_outputs
    ]
    displayed_outputs = [
        {
            "field": output["field"],
            "values": [],
            "represented_by": "output_changes",
        }
        if output["field"] == "LedgerModule.positions"
        and any(change.get("field") == output["field"] for change in output_changes)
        else output
        for output in outputs_after
    ]
    record = {
        "phase": "step",
        "timestamp": before.get("timestamp", ""),
        "event_kind": f.event_kind.name if f.event_kind is not None else "",
        "current_event": before.get("current_event", {}),
        "flow_name": f.effective_description or "",
        "flow_id": f.name or "",
        "flow_phase": f.phase.value,
        "description": getattr(f, "description", "") or "",
        "inputs": before.get("inputs", []),
        "outputs": displayed_outputs,
        "output_changes": output_changes,
        "strategies": before.get("strategies", []),
        "ledgers_before": _audit_ledger_topology(before.get("ledgers_before", [])),
        "ledgers_after": _audit_ledger_topology(ledgers_after),
        "ledger_changes": displayed_ledger_changes,
        "event_payloads": (
            []
            if event_payload_changes or not f.event_payload_inputs
            else before.get("event_payloads", [])
        ),
        "event_payloads_after": [],
        "event_payload_changes": event_payload_changes,
        "event_queue": _audit_event_queue_head(state, ctx._event_queue),
        "input_contract_violations": [
            *direct_contract_violations,
            *ledger_contract_violations,
        ],
    }
    dmtm = _audit_dmtm_step(f, before, ledger_changes, outputs_after)
    if dmtm is not None:
        record["dmtm"] = dmtm
    step_callback(record)



def make_dispatcher(
    ordered_flows: list[ResolvedFlow],
    state: "BacktestRunState",
    event_queue: EventQueue,
    tracker: "_ProgressTracker | None" = None,
    audit_contract: bool = False,
    enforce_contract: bool = False,
    flow_strategies: dict[str, frozenset["Strategy"]] | None = None,
    step_callback: "Callable[[dict[str, Any]], None] | None" = None,
    profiler: "BacktestProfiler | None" = None,
) -> Callable[[list[EventDraft]], None]:
    applicable_by_flow = flow_strategies or _flow_strategy_sets(state, ordered_flows)
    strategies_by_ledger = _ledger_strategy_sets(state)

    def handler(batch: list[EventDraft]) -> None:
        batch = _actionable_event_batch(state, batch)
        if not batch:
            return
        timestamp = batch[0].timestamp
        # A strategy can appear more than once in one batch (e.g. several
        # ORDER events for different products at the same timestamp) --
        # group by strategy without dropping any draft. One pass, O(batch).
        drafts_by_strategy: dict["Strategy", list[EventDraft]] = {}
        drafts_by_ledger: dict[Any, list[EventDraft]] = {}
        ledger_active_strategies: set["Strategy"] = set()
        for draft in batch:
            if draft.strategy is not None:
                drafts_by_strategy.setdefault(draft.strategy, []).append(draft)
            if draft.ledger is not None:
                drafts_by_ledger.setdefault(draft.ledger, []).append(draft)
                ledger_active_strategies.update(strategies_by_ledger.get(_ledger_identity_for_scheduler(draft.ledger), frozenset()))
            if draft.strategy is None and draft.ledger is None:
                raise SchedulerError(
                    f"{draft.kind.name} event at {draft.timestamp} has neither strategy nor ledger"
                )
        all_active = frozenset(set(drafts_by_strategy) | ledger_active_strategies)
        all_active_ledgers = frozenset(drafts_by_ledger)
        # ONE ctx for the whole batch -- this is what lets one Flow's
        # ctx.set_for(...) be read by a later Flow in the same batch (e.g.
        # LedgerModule.equity_on_signal -> OrderConstructModule.size_order).
        # active_strategies is narrowed per Flow call (different Flows can
        # apply to different subsets), but _values/_values_by_strategy
        # persist across the whole batch.
        ctx = FlowContext(
            timestamp=timestamp, event_queue=event_queue,
            event_kind=batch[0].kind,
            active_strategies=all_active, active_ledgers=all_active_ledgers,
            drafts_by_strategy=drafts_by_strategy,
            drafts_by_ledger=drafts_by_ledger,
            audit_contract=audit_contract,
            enforce_contract=enforce_contract,
        )
        for f in ordered_flows:
            applicable = all_active & applicable_by_flow.get(f.name, frozenset())
            if not applicable:
                continue
            ctx.active_strategies = applicable
            if tracker is not None:
                tracker.activity(f, timestamp=timestamp, phase="event_replay", strategies=applicable)
            before = _step_before_flow(
                f, state, ctx, timestamp, step_callback, applicable, all_active_ledgers,
            )
            _compute_with_optional_profiler(
                profiler,
                f,
                state=state,
                ctx=ctx,
                timestamp=timestamp,
                strategies=applicable,
            )
            _step_after_flow(f, state, ctx, step_callback, before)
            if tracker is not None:
                tracker.tick(f.effective_description, phase=f.phase)
        if tracker is not None and batch and batch[0].kind is EventKind.SIGNAL:
            tracker.signal_batch_done(len(batch))
    return handler


def _unwrap_order_attempt(payload: Any) -> Any:
    from .order import OrderAttempt

    return payload.order if isinstance(payload, OrderAttempt) else payload


def _actionable_event_batch(
    state: "BacktestRunState",
    batch: list[EventDraft],
) -> list[EventDraft]:
    if not batch:
        return batch
    actionable = [
        draft for draft in batch
        if draft.dispatch_guard is None or draft.dispatch_guard(state, draft)
    ]
    if not actionable or actionable[0].kind is not EventKind.ORDER:
        return actionable
    from .order import OrderAttempt

    actionable_orders: list[EventDraft] = []
    for draft in actionable:
        attempt = draft.payload
        if not isinstance(attempt, OrderAttempt):
            actionable_orders.append(draft)
            continue
        if not state.order_store.attempt_is_actionable(attempt):
            continue
        attempt.order.set("active_attempt_id", attempt.attempt_id)
        attempt.order.set("active_market_timestamp", attempt.market_timestamp)
        actionable_orders.append(draft)
    return actionable_orders


def _ledger_identity_for_scheduler(ledger: Any) -> Any:
    from .ledger import ledger_identity

    return ledger_identity(ledger)


def _ledger_strategy_sets(state: "BacktestRunState") -> dict[Any, frozenset["Strategy"]]:
    from tools.testers.backtest.modules.strategy_book import strategy_book_store_for

    store = strategy_book_store_for(state)
    result: dict[Any, set["Strategy"]] = {}
    for strategy in state.strategy_configs:
        for ledger in store.ledgers_for_strategy(state, strategy):
            result.setdefault(_ledger_identity_for_scheduler(ledger), set()).add(strategy)
    return {ledger: frozenset(strategies) for ledger, strategies in result.items()}


def _flow_strategy_sets(
    state: "BacktestRunState",
    flows: list[ResolvedFlow] | tuple[ResolvedFlow, ...],
) -> dict[str, frozenset["Strategy"]]:
    flow_names = {flow.name for flow in flows}
    result: dict[str, set["Strategy"]] = {name: set() for name in flow_names}
    for strategy, config in state.strategy_configs.items():
        for flow_name in config.active_flow_names & flow_names:
            result.setdefault(flow_name, set()).add(strategy)
    return {name: frozenset(strategies) for name, strategies in result.items()}


def _all_flow_strategy_sets(
    state: "BacktestRunState",
    groups: dict[tuple[Phase, EventKind | None], list[ResolvedFlow]],
) -> dict[str, frozenset["Strategy"]]:
    flows: list[ResolvedFlow] = []
    for ordered_flows in groups.values():
        flows.extend(ordered_flows)
    return _flow_strategy_sets(state, flows)


def _strategies_using_flow(
    state: "BacktestRunState",
    flow_name: str,
    flow_strategies: dict[str, frozenset["Strategy"]] | None = None,
) -> frozenset["Strategy"]:
    if flow_strategies is not None:
        return flow_strategies.get(flow_name, frozenset())
    return frozenset(
        strategy for strategy in state.strategy_configs
        if flow_name in state.config_for(strategy).active_flow_names
    )


def _pre_post_applicable_strategies(
    state: "BacktestRunState",
    flow: ResolvedFlow,
    flow_strategies: dict[str, frozenset["Strategy"]] | None = None,
) -> frozenset["Strategy"]:
    return _strategies_using_flow(state, flow.name, flow_strategies)





def _mode_info_for_flow(
    state: "BacktestRunState",
    flow: ResolvedFlow,
    strategies: frozenset["Strategy"],
) -> dict[str, Any]:
    if not strategies:
        return {}
    values_by_name: dict[str, set[str]] = {}
    for strategy in strategies:
        config = state.config_for(strategy)
        for ref, value in config.field_values.items():
            name = str(getattr(ref, "name", ref) or "")
            values_by_name.setdefault(name, set()).add(_mode_value_text(value))
    mode_info: dict[str, Any] = {}
    for name in sorted(values_by_name):
        values = sorted(values_by_name[name])
        mode_info[name] = values[0] if len(values) == 1 else f"多值[{len(values)}]"
    return mode_info





def _mode_value_text(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return f"{len(value)}项"
    if isinstance(value, dict):
        return f"{len(value)}项"
    return type(value).__name__


_step_mode_globals = {"enabled": False}


def _set_state_store_guards(state: "BacktestRunState", enabled: bool) -> list[tuple[Any, bool]]:
    """Enable opt-in store mutation guards during step/contract-audit runs.

    FlowContext can audit declared FieldRef reads/writes directly. Long-lived
    state stores need their own guard because direct attribute assignment would
    otherwise bypass Flow declarations and be invisible to step-mode audit.
    Stores that participate expose set_guarded_writes_enabled(bool).
    """
    restored: list[tuple[Any, bool]] = []
    object.__setattr__(state, "_store_guards_enabled", bool(enabled))
    stores = [getattr(state, "market_data_store", None), getattr(state, "cash_pool_store", None)]
    stores.extend(getattr(state, "ledgers", {}).values())
    for store in stores:
        setter = getattr(store, "set_guarded_writes_enabled", None)
        if not callable(setter):
            continue
        previous = bool(getattr(store, "_guarded_writes_enabled", False))
        setter(enabled)
        restored.append((store, previous))
    return restored


def _restore_state_store_guards(state: "BacktestRunState", restored: list[tuple[Any, bool]]) -> None:
    seen: set[int] = set()
    for store, previous in restored:
        seen.add(id(store))
        setter = getattr(store, "set_guarded_writes_enabled", None)
        if callable(setter):
            setter(previous)
    object.__setattr__(state, "_store_guards_enabled", False)
    for ledger in getattr(state, "ledgers", {}).values():
        if id(ledger) in seen:
            continue
        setter = getattr(ledger, "set_guarded_writes_enabled", None)
        if callable(setter):
            setter(False)


def run(
    state: "BacktestRunState",
    event_queue: EventQueue,
    resolved_flows: list[ResolvedFlow],
    progress: Callable[[int, int, str], None] | None = None,
    activity_sink: ProgressSink | None = None,
    audit_flow_contract: bool = False,
    enforce_flow_contract: bool = False,
    step_mode: bool = False,
    step_callback: "Callable[[dict[str, Any]], None] | None" = None,
    profiler: "BacktestProfiler | None" = None,
) -> None:
    previous_step_mode = bool(_step_mode_globals.get("enabled", False))
    _step_mode_globals["enabled"] = step_mode
    guarded_stores = _set_state_store_guards(state, step_mode or audit_flow_contract or enforce_flow_contract)
    try:
        _run_with_guards(
            state,
            event_queue,
            resolved_flows,
            progress=progress,
            activity_sink=activity_sink,
            audit_flow_contract=audit_flow_contract,
            enforce_flow_contract=enforce_flow_contract,
            step_callback=step_callback,
            profiler=profiler,
        )
    finally:
        if profiler is not None:
            profiler.reset()
        observer = getattr(state, "margin_execution_observer", None)
        if observer is not None:
            observer.reset()
        _restore_state_store_guards(state, guarded_stores)
        _step_mode_globals["enabled"] = previous_step_mode


def _run_with_guards(
    state: "BacktestRunState",
    event_queue: EventQueue,
    resolved_flows: list[ResolvedFlow],
    progress: Callable[[int, int, str], None] | None = None,
    activity_sink: ProgressSink | None = None,
    audit_flow_contract: bool = False,
    enforce_flow_contract: bool = False,
    step_callback: "Callable[[dict[str, Any]], None] | None" = None,
    profiler: "BacktestProfiler | None" = None,
) -> None:
    """Invariant: run() itself never calls event_queue.push_event directly
    — events are only ever registered by some Flow's compute via
    ctx.set()/ctx.set_for() (FlowContext._push_if_event). Any future change
    that wants to conveniently push an event from inside this function
    means the design has drifted — go fix a Flow, not this function.

    `progress(completed, total, label)` is kept for legacy coarse callers.
    `activity_sink` is the native UI contract: manifest + activity +
    signal-progress, with no flow-count totals exposed to the user."""
    groups = sort_and_validate(resolved_flows)
    pre_replay_flows = groups.get((Phase.PRE_REPLAY, None), ())
    post_replay_flows = groups.get((Phase.POST_REPLAY, None), ())
    flow_strategies = _all_flow_strategy_sets(state, groups)
    tracker = _ProgressTracker(state, progress, activity_sink, event_queue, flow_strategies)
    tracker.emit_manifest(groups, state, flow_strategies)
    applicable_pre_flows = [
        f for f in pre_replay_flows
        if _pre_post_applicable_strategies(state, f, flow_strategies)
    ]
    applicable_post_flows = [
        f for f in post_replay_flows
        if _pre_post_applicable_strategies(state, f, flow_strategies)
    ]
    tracker.set_phase_totals(pre_total=len(applicable_pre_flows), post_total=len(applicable_post_flows))

    for (phase, event_kind), ordered_flows in groups.items():
        if phase is Phase.PER_EVENT:
            event_queue.set_dispatcher(
                cast(EventKind, event_kind),
                make_dispatcher(
                    ordered_flows,
                    state,
                    event_queue,
                    tracker,
                    audit_flow_contract,
                    enforce_flow_contract,
                    flow_strategies,
                    step_callback=step_callback,
                    profiler=profiler,
                ),
            )

    ctx = FlowContext(
        timestamp=None,
        event_queue=event_queue,
        audit_contract=audit_flow_contract,
        enforce_contract=enforce_flow_contract,
    )
    for f in pre_replay_flows:
        applicable = _pre_post_applicable_strategies(state, f, flow_strategies)
        if not applicable:
            continue
        ctx.active_strategies = applicable
        tracker.activity(f, timestamp=None, phase="pre_replay", strategies=applicable)
        before = _step_before_flow(f, state, ctx, None, step_callback, applicable, ctx.active_ledgers)
        _compute_with_optional_profiler(
            profiler,
            f,
            state=state,
            ctx=ctx,
            timestamp=None,
            strategies=applicable,
        )
        _step_after_flow(f, state, ctx, step_callback, before)
        tracker.phase_flow_done(phase="pre_replay")
        tracker.tick(f.effective_description, phase=Phase.PRE_REPLAY)

    tracker.note_signal_queue_ready()
    event_queue.run_until_drained()
    tracker.event_replay_done()

    ctx = FlowContext(
        timestamp=None,
        event_queue=event_queue,
        audit_contract=audit_flow_contract,
        enforce_contract=enforce_flow_contract,
    )
    for f in post_replay_flows:
        applicable = _pre_post_applicable_strategies(state, f, flow_strategies)
        if not applicable:
            continue
        ctx.active_strategies = applicable
        tracker.activity(f, timestamp=None, phase="post_replay", strategies=applicable)
        before = _step_before_flow(f, state, ctx, None, step_callback, applicable, ctx.active_ledgers)
        _compute_with_optional_profiler(
            profiler,
            f,
            state=state,
            ctx=ctx,
            timestamp=None,
            strategies=applicable,
        )
        _step_after_flow(f, state, ctx, step_callback, before)
        tracker.phase_flow_done(phase="post_replay")
        tracker.tick(f.effective_description, phase=Phase.POST_REPLAY)
    if profiler is not None:
        profiler.flush_flows(state)
    observer = getattr(state, "margin_execution_observer", None)
    if observer is not None:
        observer.flush(state)
    tracker.complete()


def _compute_flow(flow: ResolvedFlow, state: "BacktestRunState", ctx: FlowContext) -> None:
    ctx.enter_flow(flow)
    enter_audit = getattr(state, "enter_flow_contract_audit", None)
    restore_audit = getattr(state, "restore_flow_contract_audit", None)
    previous_audit = (
        enter_audit(ctx, ctx.contract_audit_token())
        if callable(enter_audit) and (ctx._audit_contract or ctx._enforce_contract)
        else None
    )
    try:
        flow.compute(state, ctx)
    finally:
        if callable(restore_audit) and (ctx._audit_contract or ctx._enforce_contract):
            restore_audit(previous_audit)
        ctx.exit_flow()


def _activity_phase(phase: Phase) -> str:
    if phase is Phase.PER_EVENT:
        return "event_replay"
    return phase.value


def _activity_phase_for_flow(flow: ResolvedFlow) -> str:
    return _activity_phase(flow.phase)


def _activity_message(timestamp: str, label: str) -> str:
    if timestamp:
        return f"{timestamp} 正在{label}"
    return f"正在{label}"


def activity_manifest_from_groups(
    groups: dict[tuple[Phase, EventKind | None], list[ResolvedFlow]],
    state: "BacktestRunState",
    flow_strategies: dict[str, frozenset["Strategy"]] | None = None,
) -> list[dict[str, Any]]:
    phase_specs: list[dict[str, Any]] = []
    pre_all = [
        flow for flow in groups.get((Phase.PRE_REPLAY, None), ())
        if _flow_applicable_to_any_strategy(state, flow, flow_strategies)
    ]
    phase_specs.append(_phase_spec("pre_replay", pre_all))

    event_flows: list[ResolvedFlow] = []
    for (phase, _kind), flows in groups.items():
        if phase is Phase.PER_EVENT:
            event_flows.extend(
                flow for flow in flows
                if _flow_applicable_to_any_strategy(state, flow, flow_strategies)
            )
    event_flows = sorted(event_flows, key=lambda f: (f.order, f.event_kind or EventKind.SIGNAL, f.name))
    event_flows = _dedupe_manifest_flows(event_flows)
    phase_specs.append(_phase_spec("event_replay", event_flows))

    post = [
        flow for flow in groups.get((Phase.POST_REPLAY, None), ())
        if _flow_applicable_to_any_strategy(state, flow, flow_strategies)
    ]
    phase_specs.append(_phase_spec("post_replay", post))
    return phase_specs


def _flow_applicable_to_any_strategy(
    state: "BacktestRunState",
    flow: ResolvedFlow,
    flow_strategies: dict[str, frozenset["Strategy"]] | None = None,
) -> bool:
    return bool(_strategies_using_flow(state, flow.name, flow_strategies))


def _dedupe_manifest_flows(flows: list[ResolvedFlow]) -> list[ResolvedFlow]:
    result: list[ResolvedFlow] = []
    seen: set[str] = set()
    for flow in flows:
        # A logical flow can be registered under multiple event kinds (for
        # example live factor handling observes BAR events and publishes SIGNAL
        # values). The progress diagram should show the logical user-facing
        # operation once.
        key = flow.name
        if key in seen:
            continue
        seen.add(key)
        result.append(flow)
    return result


def _phase_spec(key: str, flows: list[ResolvedFlow] | tuple[ResolvedFlow, ...]) -> dict[str, Any]:
    visible_flows = [flow for flow in flows if not flow.input_materialization]
    return {
        "key": key,
        "label": phase_label(key),
        "flows": [
            {
                "phase": key,
                "flow_key": flow.activity_key,
                "flow_name": flow.name,
                "flow_label": flow.effective_description,
                "display_order": idx,
                "event_kind": flow.event_kind.name if flow.event_kind is not None else "",
            }
            for idx, flow in enumerate(visible_flows, start=1)
        ],
    }
