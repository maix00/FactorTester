"""Structured, serializable order-flow audit records."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson

from tools.testers.backtest.engines.native.order import Order

from .values import float_or_none, timestamp_key
from .audit_stream import OrderFlowRecordStream


STREAM_BATCH_SIZE = 64


@dataclass
class OrderFlowStore:
    _next_id_by_strategy: dict[str, int] = field(default_factory=dict)
    _next_group_by_strategy: dict[str, int] = field(default_factory=dict)
    records_by_strategy: dict[Any, list[dict[str, Any]]] = field(default_factory=dict)
    records_by_order: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    _stream_root: Path | None = field(default=None, init=False, repr=False)
    _stream_handles: dict[Any, Any] = field(default_factory=dict, init=False, repr=False)
    _stream_paths: dict[Any, Path] = field(default_factory=dict, init=False, repr=False)
    _stream_counts: dict[Any, int] = field(default_factory=dict, init=False, repr=False)
    _stream_buffers: dict[Any, list[dict[str, Any]]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def enable_streaming(self, root: Path | str | None = None) -> None:
        if self._stream_root is not None:
            return
        if root is None:
            root = tempfile.mkdtemp(prefix="factortester-order-flow-")
            self._stream_root = Path(root)
        else:
            self._stream_root = Path(root)
            self._stream_root.mkdir(parents=True, exist_ok=False)

    @property
    def streaming_enabled(self) -> bool:
        return self._stream_root is not None

    def next_order_id(self, strategy: Any, timestamp: Any) -> str:
        alias = str(getattr(strategy, "alias", strategy))
        next_id = self._next_id_by_strategy.get(alias, 0) + 1
        self._next_id_by_strategy[alias] = next_id
        return f"{alias}-{timestamp_key(timestamp)}-{next_id}"

    def next_group_id(self, strategy: Any, timestamp: Any) -> str:
        alias = str(getattr(strategy, "alias", strategy))
        next_id = self._next_group_by_strategy.get(alias, 0) + 1
        self._next_group_by_strategy[alias] = next_id
        return f"{alias}-{timestamp_key(timestamp)}-group-{next_id}"

    def record(
        self,
        order: Order,
        *,
        step: str,
        label: str,
        timestamp: Any | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        order_id = _ensure_order_id(self, order, timestamp)
        record = {
            "order_id": order_id,
            "order_group_id": order.order_group_id,
            "parent_intent_id": order.parent_intent_id,
            "strategy_id": str(getattr(order.strategy, "alias", order.strategy)),
            "timestamp": timestamp_key(timestamp or order.timestamp),
            "step": step,
            "label": label,
            "product": str(getattr(order.instrument, "name", order.instrument)),
            "quantity": float(order.quantity or 0.0),
            "intent_quantity": float(order.intent_quantity or 0.0),
            "requested_quantity": float(order.requested_quantity or 0.0),
            "filled_quantity": float(order.filled_quantity),
            "remaining_quantity": float(order.remaining_quantity),
            "unfilled_quantity": float(order.unfilled_quantity),
            "status": order.status.value,
            "leg_role": order.leg_role.value,
            "offset": order.offset.value,
            "execution_effect": order.execution_effect.value,
            "revision": int(order.revision),
            "effective_price": float_or_none(order.get("effective_price")),
            "fee_cost": float_or_none(order.get("fee_cost")),
            "reject_reason": order.reject_reason or order.get("reject_reason"),
            "details": dict(details or {}),
        }
        self._store_record(order.strategy, order_id, record)

    def records_for_strategy(self, strategy: Any):
        if self._stream_root is not None:
            self._flush_strategy(strategy)
            return OrderFlowRecordStream(
                self._stream_path(strategy),
                self._stream_counts.get(strategy, 0),
            )
        return list(self.records_by_strategy.get(strategy, ()))

    def records_for_order(self, order_id: str) -> list[dict[str, Any]]:
        if self._stream_root is not None:
            return [
                record
                for strategy in self._stream_paths
                for record in self.records_for_strategy(strategy)
                if str(record.get("order_id") or "") == str(order_id)
            ]
        return list(self.records_by_order.get(str(order_id), ()))

    def record_strategy_step(
        self,
        strategy: Any,
        *,
        timestamp: Any,
        step: str,
        label: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        record = {
            "order_id": "",
            "strategy_id": str(getattr(strategy, "alias", strategy)),
            "timestamp": timestamp_key(timestamp),
            "step": step,
            "label": label,
            "product": "",
            "quantity": None,
            "intent_quantity": None,
            "status": "",
            "effective_price": None,
            "fee_cost": None,
            "reject_reason": None,
            "details": dict(details or {}),
        }
        self._store_record(strategy, None, record)

    def cleanup_streaming(self) -> None:
        for strategy in tuple(self._stream_buffers):
            self._flush_strategy(strategy)
        for handle in self._stream_handles.values():
            handle.close()
        self._stream_handles.clear()
        root = self._stream_root
        self._stream_root = None
        self._stream_paths.clear()
        self._stream_counts.clear()
        self._stream_buffers.clear()
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)

    def _store_record(
        self,
        strategy: Any,
        order_id: str | None,
        record: dict[str, Any],
    ) -> None:
        if self._stream_root is None:
            if order_id is not None:
                self.records_by_order.setdefault(order_id, []).append(record)
            self.records_by_strategy.setdefault(strategy, []).append(record)
            return
        buffer = self._stream_buffers.setdefault(strategy, [])
        buffer.append(record)
        self._stream_counts[strategy] = self._stream_counts.get(strategy, 0) + 1
        if len(buffer) < STREAM_BATCH_SIZE:
            return
        self._write_stream_buffer(strategy)

    def _write_stream_buffer(self, strategy: Any) -> None:
        buffer = self._stream_buffers.get(strategy)
        if not buffer:
            return
        handle = self._stream_handles.get(strategy)
        if handle is None:
            path = self._stream_path(strategy)
            handle = path.open("ab", buffering=1024 * 1024)
            self._stream_handles[strategy] = handle
        handle.write(orjson.dumps(
            buffer,
            default=_stream_json_default,
        ))
        handle.write(b"\n")
        buffer.clear()

    def _stream_path(self, strategy: Any) -> Path:
        path = self._stream_paths.get(strategy)
        if path is not None:
            return path
        if self._stream_root is None:
            raise RuntimeError("order-flow streaming is not enabled")
        alias = str(getattr(strategy, "alias", strategy))
        token = hashlib.sha256(alias.encode("utf-8")).hexdigest()[:16]
        path = self._stream_root / f"{token}.jsonl"
        self._stream_paths[strategy] = path
        return path

    def _flush_strategy(self, strategy: Any) -> None:
        self._write_stream_buffer(strategy)
        handle = self._stream_handles.get(strategy)
        if handle is not None:
            handle.flush()


def _stream_json_default(value: Any) -> Any:
    if value.__class__.__module__.startswith("numpy"):
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            pass
    return str(value)


def _ensure_order_id(store: OrderFlowStore, order: Order, timestamp: Any) -> str:
    order_id = str(order.order_id or order.get("order_flow_id", "") or "")
    if order_id:
        return order_id
    order_id = store.next_order_id(order.strategy, timestamp or order.timestamp)
    order.order_id = order_id
    return order_id
