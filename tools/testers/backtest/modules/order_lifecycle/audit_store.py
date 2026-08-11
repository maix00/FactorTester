"""Structured, serializable order-flow audit records."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson

from tools.testers.backtest.engines.native.order import Order

from .values import float_or_none, timestamp_key
from .audit_stream import (
    OrderFlowRecordStream,
    _sorted_checksum_rows,
    checksum_row_bytes,
)


STREAM_BATCH_SIZE = 64
TEXT_CACHE_LIMIT = 2048


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
    _timestamp_text_cache: OrderedDict[int, tuple[Any, str]] = field(
        default_factory=OrderedDict, init=False, repr=False,
    )
    _strategy_text_cache: OrderedDict[int, tuple[Any, str]] = field(
        default_factory=OrderedDict, init=False, repr=False,
    )
    _product_text_cache: OrderedDict[int, tuple[Any, str]] = field(
        default_factory=OrderedDict, init=False, repr=False,
    )
    # A streaming run used to reread and JSON-decode every spool record at
    # projection time solely to build ``execution_trace_checksum``.  Keep one
    # digest plus the current timestamp batch while records are produced so
    # projection can consume the already-computed value.  ``_checksum_invalid``
    # preserves the old fallback for an unexpected out-of-order producer.
    _checksum_by_strategy: dict[Any, Any] = field(
        default_factory=dict, init=False, repr=False,
    )
    _checksum_timestamp_by_strategy: dict[Any, str] = field(
        default_factory=dict, init=False, repr=False,
    )
    _checksum_rows_by_strategy: dict[Any, list[dict[str, Any]]] = field(
        default_factory=dict, init=False, repr=False,
    )
    _checksum_invalid: set[Any] = field(default_factory=set, init=False, repr=False)
    _checksum_enabled: bool = field(default=True, init=False, repr=False)
    _records_enabled: bool = field(default=True, init=False, repr=False)

    def enable_streaming(
        self,
        root: Path | str | None = None,
        *,
        compute_checksum: bool = True,
        retain_records: bool = True,
    ) -> None:
        if self._stream_root is not None:
            return
        if root is None:
            root = tempfile.mkdtemp(prefix="factortester-order-flow-")
            self._stream_root = Path(root)
        else:
            self._stream_root = Path(root)
            self._stream_root.mkdir(parents=True, exist_ok=False)
        self._checksum_enabled = bool(compute_checksum)
        self._records_enabled = bool(retain_records)

    @property
    def streaming_enabled(self) -> bool:
        return self._stream_root is not None

    @property
    def records_enabled(self) -> bool:
        """Whether per-record payloads are retained for this run.

        Summary retention still counts lifecycle records, but it does not
        store their fields.  Hot producers can use this read-only flag to
        avoid constructing detail dictionaries that ``record`` will discard.
        """
        return self._records_enabled

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
        if not self._records_enabled:
            self._stream_counts[order.strategy] = (
                self._stream_counts.get(order.strategy, 0) + 1
            )
            return
        strategy_id = self._strategy_text(order.strategy)
        record_timestamp = self._timestamp_text(timestamp or order.timestamp)
        # Native Order.get is a thin wrapper around fields.get.  Keep the
        # wrapper fallback for lightweight test doubles, but use the concrete
        # dict directly on the production path and compute the quantity
        # properties once.  The emitted schema and values are unchanged.
        fields = getattr(order, "fields", None)
        if isinstance(fields, dict):
            effective_price = fields.get("effective_price")
            fee_cost = fields.get("fee_cost")
            field_reject_reason = fields.get("reject_reason")
        else:
            effective_price = order.get("effective_price")
            fee_cost = order.get("fee_cost")
            field_reject_reason = order.get("reject_reason")
        unfilled_quantity = order.unfilled_quantity
        remaining_quantity = order.remaining_quantity
        record = {
            "order_id": order_id,
            "order_group_id": order.order_group_id,
            "parent_intent_id": order.parent_intent_id,
            "strategy_id": strategy_id,
            "timestamp": record_timestamp,
            "step": step,
            "label": label,
            "product": self._product_text(order.instrument),
            "quantity": float(order.quantity or 0.0),
            "intent_quantity": float(order.intent_quantity or 0.0),
            "requested_quantity": float(order.requested_quantity or 0.0),
            "filled_quantity": float(order.filled_quantity),
            "remaining_quantity": float(remaining_quantity),
            "unfilled_quantity": float(unfilled_quantity),
            "status": order.status.value,
            "leg_role": order.leg_role.value,
            "offset": order.offset.value,
            "execution_effect": order.execution_effect.value,
            "revision": int(order.revision),
            "effective_price": float_or_none(effective_price),
            "fee_cost": float_or_none(fee_cost),
            "reject_reason": order.reject_reason or field_reject_reason,
            "details": dict(details or {}),
        }
        self._store_record(order.strategy, order_id, record)

    def _timestamp_text(self, value: Any) -> str:
        if value is None:
            return ""
        key = id(value)
        cached = self._timestamp_text_cache.pop(key, None)
        if cached is not None and cached[0] is value:
            self._timestamp_text_cache[key] = cached
            return cached[1]
        text = timestamp_key(value)
        # Retain the value alongside its id so a later object cannot inherit
        # a stale string if Python reuses an id after an unusual adapter path.
        self._timestamp_text_cache[key] = (value, text)
        if len(self._timestamp_text_cache) > TEXT_CACHE_LIMIT:
            self._timestamp_text_cache.popitem(last=False)
        return text

    def _strategy_text(self, strategy: Any) -> str:
        key = id(strategy)
        cached = self._strategy_text_cache.pop(key, None)
        if cached is not None and cached[0] is strategy:
            self._strategy_text_cache[key] = cached
            return cached[1]
        text = str(getattr(strategy, "alias", strategy))
        self._strategy_text_cache[key] = (strategy, text)
        if len(self._strategy_text_cache) > TEXT_CACHE_LIMIT:
            self._strategy_text_cache.popitem(last=False)
        return text

    def _product_text(self, product: Any) -> str:
        key = id(product)
        cached = self._product_text_cache.pop(key, None)
        if cached is not None and cached[0] is product:
            self._product_text_cache[key] = cached
            return cached[1]
        text = str(getattr(product, "name", product))
        self._product_text_cache[key] = (product, text)
        if len(self._product_text_cache) > TEXT_CACHE_LIMIT:
            self._product_text_cache.popitem(last=False)
        return text

    def records_for_strategy(self, strategy: Any):
        if self._stream_root is not None:
            if self._checksum_enabled:
                self._finalize_checksum(strategy)
            self._flush_strategy(strategy)
            return OrderFlowRecordStream(
                self._stream_path(strategy),
                self._stream_counts.get(strategy, 0),
                checksum=(
                    None
                    if not self._checksum_enabled or strategy in self._checksum_invalid
                    else self._checksum_hex(strategy)
                ),
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
        if not self._records_enabled:
            self._stream_counts[strategy] = (
                self._stream_counts.get(strategy, 0) + 1
            )
            return
        record = {
            "order_id": "",
            "strategy_id": self._strategy_text(strategy),
            "timestamp": self._timestamp_text(timestamp),
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
        self._checksum_by_strategy.clear()
        self._checksum_timestamp_by_strategy.clear()
        self._checksum_rows_by_strategy.clear()
        self._checksum_invalid.clear()
        self._checksum_enabled = True
        self._records_enabled = True
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)

    def _store_record(
        self,
        strategy: Any,
        order_id: str | None,
        record: dict[str, Any],
    ) -> None:
        if not self._records_enabled:
            self._stream_counts[strategy] = (
                self._stream_counts.get(strategy, 0) + 1
            )
            return
        if self._stream_root is not None and self._checksum_enabled:
            self._record_checksum(strategy, record)
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

    def _record_checksum(self, strategy: Any, record: dict[str, Any]) -> None:
        """Accumulate the stable execution-trace checksum in timestamp order.

        Order-flow producers dispatch monotonically by event timestamp.  Rows
        sharing one timestamp are held until the timestamp changes, then
        sorted using the same primary/tie semantics as the historical replay
        path.  If a caller violates that invariant, defer to the old stream
        replay instead of changing the checksum contract.
        """
        if strategy in self._checksum_invalid:
            return
        timestamp = str(record.get("timestamp") or "")
        previous = self._checksum_timestamp_by_strategy.get(strategy)
        if previous is not None and timestamp < previous:
            self._checksum_invalid.add(strategy)
            self._checksum_rows_by_strategy.pop(strategy, None)
            self._checksum_by_strategy.pop(strategy, None)
            return
        digest = self._checksum_by_strategy.get(strategy)
        if digest is None:
            digest = hashlib.sha256()
            self._checksum_by_strategy[strategy] = digest
        if previous is not None and timestamp != previous:
            self._finalize_checksum_batch(strategy)
        self._checksum_timestamp_by_strategy[strategy] = timestamp
        self._checksum_rows_by_strategy.setdefault(strategy, []).append(record)

    def _finalize_checksum_batch(self, strategy: Any) -> None:
        rows = self._checksum_rows_by_strategy.get(strategy)
        if not rows:
            return
        digest = self._checksum_by_strategy[strategy]
        for row in _sorted_checksum_rows(iter(rows)):
            digest.update(checksum_row_bytes(row))
        rows.clear()

    def _finalize_checksum(self, strategy: Any) -> None:
        if strategy in self._checksum_invalid:
            return
        self._finalize_checksum_batch(strategy)

    def _checksum_hex(self, strategy: Any) -> str | None:
        digest = self._checksum_by_strategy.get(strategy)
        if digest is None:
            return None
        # hashlib objects cannot be finalized in-place; copying keeps the
        # store reusable if a projection is requested more than once.
        return digest.copy().hexdigest()

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
