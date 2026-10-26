"""Lightweight input protocols shared by batch, incremental and Nautilus."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

ProductId = str


@dataclass(frozen=True)
class TermPoint:
    values: Mapping[str, float]
    days_to_maturity: float | None = None
    maturity_ns: int | None = None
    rank: int | None = None


@dataclass(frozen=True)
class TermCurve:
    product_id: ProductId
    points: tuple[TermPoint, ...]
    available_at_ns: int | None = None

    def rows(self) -> list[dict[str, Any]]:
        ordered = sorted(
            enumerate(self.points),
            key=lambda item: (item[1].rank if item[1].rank is not None else item[0]),
        )
        rows = []
        for _, point in ordered:
            row = dict(point.values)
            if point.days_to_maturity is not None:
                row["DAYS_TO_MATURITY"] = float(point.days_to_maturity)
            if point.maturity_ns is not None:
                row["MATURITY_NS"] = int(point.maturity_ns)
            rows.append(row)
        return rows


@dataclass(frozen=True)
class CategoryMembership:
    product_id: ProductId
    labels: frozenset[str]
    effective_at_ns: int | None = None

    def active_at(self, timestamp_ns: int | None) -> bool:
        return self.effective_at_ns is None or timestamp_ns is None or self.effective_at_ns <= timestamp_ns


@dataclass(frozen=True)
class MatchRequest:
    current: float
    candidates: tuple[tuple[int, float], ...]
    predicate: Any
    scope_start: int
    scope_end: int
    default: float = float("nan")
