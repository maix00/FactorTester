"""Disk-backed order-flow records for long native backtests."""

from __future__ import annotations

import json
from itertools import groupby
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any


class OrderFlowRecordStream(Sequence[dict[str, Any]]):
    """Replayable JSON array backed by one newline-delimited spool file."""

    def __init__(
        self,
        path: Path,
        count: int,
        *,
        checksum: str | None = None,
    ) -> None:
        self.path = path
        self.count = int(count)
        # The run-scoped OrderFlowStore can finalize this digest while records
        # are being produced.  Keeping it on the replayable stream avoids
        # reopening and decoding the complete JSONL spool during result
        # projection.  ``None`` deliberately means “not available”; callers
        # then retain the historical replay-and-sort fallback.
        self._checksum = checksum

    def __len__(self) -> int:
        return self.count

    def __iter__(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    value = json.loads(line)
                    if isinstance(value, list):
                        yield from value
                    else:
                        yield value

    def __getitem__(self, index):
        if isinstance(index, slice):
            return list(self)[index]
        normalized = int(index)
        if normalized < 0:
            normalized += self.count
        if normalized < 0 or normalized >= self.count:
            raise IndexError(index)
        for offset, value in enumerate(self):
            if offset == normalized:
                return value
        raise IndexError(index)

    def checksum(self) -> str | None:
        """Return an eager checksum when the producer supplied one."""
        return self._checksum

    def iter_json_tokens(self) -> Iterator[str]:
        """Yield a valid JSON array without rebuilding records in memory."""
        yield "["
        first = True
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    value = line.strip()
                    if not value:
                        continue
                    if value.startswith("[") and value.endswith("]"):
                        value = value[1:-1]
                        if not value:
                            continue
                    if not first:
                        yield ","
                    first = False
                    yield value
        yield "]"

    def iter_checksum_rows(self) -> Iterator[dict[str, Any]]:
        """Yield the historical checksum order with bounded timestamp batches."""
        previous_timestamp = ""
        for timestamp, rows in groupby(
            self,
            key=lambda row: str(row.get("timestamp") or ""),
        ):
            if previous_timestamp and timestamp < previous_timestamp:
                raise ValueError("order-flow spool timestamps are not monotonic")
            previous_timestamp = timestamp
            yield from _sorted_checksum_rows(rows)


def _checksum_sort_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("timestamp") or ""),
        str(row.get("order_id") or ""),
        str(row.get("step") or ""),
        json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            default=_checksum_json_default,
        ),
    )


def _checksum_primary_key(row: dict[str, Any]) -> tuple[str, str]:
    """The non-tie portion of the historical checksum sort key.

    Most order-flow rows have a unique ``(order_id, step)`` pair within a
    timestamp.  The old key still serialized every row to JSON merely to
    discover that it was not a tie.  Sorting by this primary pair first and
    serializing only duplicate pairs preserves the exact order while removing
    that hot-path JSON work for the common case.
    """
    return (
        str(row.get("order_id") or ""),
        str(row.get("step") or ""),
    )


def _sorted_checksum_rows(rows: Iterator[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort one timestamp batch exactly as ``_checksum_sort_key`` does.

    The timestamp is constant inside the batch.  A stable primary sort is
    therefore equivalent to the first three components of the historical key;
    only duplicate ``(order_id, step)`` groups need the expensive canonical
    JSON tie-breaker.
    """
    ordered = sorted(rows, key=_checksum_primary_key)
    result: list[dict[str, Any]] = []
    for _pair, duplicate_rows in groupby(ordered, key=_checksum_primary_key):
        duplicate = list(duplicate_rows)
        if len(duplicate) > 1:
            duplicate.sort(key=_checksum_sort_tie_key)
        result.extend(duplicate)
    return result


def _checksum_sort_tie_key(row: dict[str, Any]) -> str:
    return json.dumps(
        row,
        ensure_ascii=False,
        sort_keys=True,
        default=_checksum_json_default,
    )


def checksum_row_bytes(row: dict[str, Any]) -> bytes:
    """Encode one row using the stable projection checksum representation."""
    return (
        str(row.get("timestamp") or "").encode("utf-8")
        + b"\0"
        + json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=_checksum_json_default,
        ).encode("utf-8")
        + b"\n"
    )


def _checksum_json_default(value: Any) -> Any:
    """Mirror the JSONL spool's numpy/scalar conversion policy."""
    if value.__class__.__module__.startswith("numpy"):
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            pass
    return str(value)
