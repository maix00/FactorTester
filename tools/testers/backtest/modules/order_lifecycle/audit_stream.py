"""Disk-backed order-flow records for long native backtests."""

from __future__ import annotations

import json
from itertools import groupby
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any


class OrderFlowRecordStream(Sequence[dict[str, Any]]):
    """Replayable JSON array backed by one newline-delimited spool file."""

    def __init__(self, path: Path, count: int) -> None:
        self.path = path
        self.count = int(count)

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
            yield from sorted(rows, key=_checksum_sort_key)


def _checksum_sort_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("timestamp") or ""),
        str(row.get("order_id") or ""),
        str(row.get("step") or ""),
        json.dumps(row, ensure_ascii=False, sort_keys=True, default=str),
    )
