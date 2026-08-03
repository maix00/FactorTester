"""Disk-backed order-flow records for long native backtests."""

from __future__ import annotations

import json
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
                    yield json.loads(line)

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
                    if not first:
                        yield ","
                    first = False
                    yield value
        yield "]"

