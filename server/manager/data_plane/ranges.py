"""Strict single HTTP byte-range parsing with capability-window checks."""

from __future__ import annotations

import re
from dataclasses import dataclass


class RangeNotSatisfiable(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ByteRange:
    start: int
    end: int
    size: int
    partial: bool

    @property
    def length(self) -> int:
        return max(0, self.end - self.start + 1)


def parse_byte_range(
    header: str,
    *,
    size: int,
    allowed_start: int = 0,
    allowed_end: int | None = None,
) -> ByteRange:
    total = int(size)
    if total < 0:
        raise ValueError("file size must not be negative")
    lower = max(0, int(allowed_start))
    upper = total - 1 if allowed_end is None else int(allowed_end)
    if lower > total or upper < lower - (1 if total == 0 else 0):
        raise RangeNotSatisfiable("capability range is invalid")
    value = str(header or "").strip()
    if not value:
        selected = ByteRange(0, total - 1, total, partial=False)
    else:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
        if match is None or (not match.group(1) and not match.group(2)):
            raise RangeNotSatisfiable("only one byte range is supported")
        if total == 0:
            raise RangeNotSatisfiable("empty file has no byte range")
        if match.group(1):
            start = int(match.group(1))
            end = int(match.group(2) or total - 1)
        else:
            suffix = int(match.group(2))
            if suffix <= 0:
                raise RangeNotSatisfiable("byte suffix must be positive")
            start = max(0, total - suffix)
            end = total - 1
        if start >= total or end < start:
            raise RangeNotSatisfiable("requested byte range is unavailable")
        selected = ByteRange(
            start=start,
            end=min(end, total - 1),
            size=total,
            partial=True,
        )
    if selected.start < lower or selected.end > upper:
        raise RangeNotSatisfiable("requested range exceeds capability window")
    return selected
