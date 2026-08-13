"""Explicit batch expansion for IC core tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from itertools import product
from math import prod
from typing import Any, Iterable

from .model import ICCoreTest


def _unique_texts(values: Iterable[Any], field_name: str) -> tuple[str, ...]:
    normalized = {str(value or "").strip() for value in values}
    if "" in normalized or not normalized:
        raise ValueError(f"{field_name} requires non-empty values")
    return tuple(sorted(normalized))


def _unique_delays(values: Iterable[Any]) -> tuple[int, ...]:
    normalized: set[int] = set()
    for value in values:
        if isinstance(value, bool):
            raise ValueError("entry_delay_bars requires non-negative integers")
        try:
            delay = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("entry_delay_bars requires non-negative integers") from exc
        if delay < 0 or delay != value:
            raise ValueError("entry_delay_bars requires non-negative integers")
        normalized.add(delay)
    if not normalized:
        raise ValueError("entry_delay_bars requires at least one value")
    return tuple(sorted(normalized))


@dataclass(frozen=True, slots=True)
class ICCoreTestBlock:
    """One explicitly requested Cartesian batch, before cell de-duplication."""

    product_scope_refs: tuple[str, ...]
    factor_refs: tuple[str, ...]
    horizons: tuple[str, ...]
    entry_delay_bars: tuple[int, ...]
    methods: tuple[str, ...]
    return_price_basis: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "product_scope_refs",
            _unique_texts(self.product_scope_refs, "product_scope_refs"),
        )
        object.__setattr__(
            self, "factor_refs", _unique_texts(self.factor_refs, "factor_refs"),
        )
        object.__setattr__(
            self, "horizons", _unique_texts(self.horizons, "horizons"),
        )
        object.__setattr__(
            self, "entry_delay_bars", _unique_delays(self.entry_delay_bars),
        )
        object.__setattr__(
            self, "methods", _unique_texts(self.methods, "methods"),
        )
        basis = str(self.return_price_basis or "").strip()
        if not basis:
            raise ValueError("return_price_basis must be non-empty text")
        object.__setattr__(self, "return_price_basis", basis)

    @property
    def cell_count(self) -> int:
        return prod((
            len(self.product_scope_refs),
            len(self.factor_refs),
            len(self.horizons),
            len(self.entry_delay_bars),
            len(self.methods),
        ))

    @property
    def block_ref(self) -> str:
        payload = json.dumps(
            self.identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()
        return f"ic-core-block:v1:{hashlib.sha256(payload).hexdigest()}"

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "product_scope_refs": list(self.product_scope_refs),
            "factor_refs": list(self.factor_refs),
            "horizons": list(self.horizons),
            "entry_delay_bars": list(self.entry_delay_bars),
            "methods": list(self.methods),
            "return_price_basis": self.return_price_basis,
        }

    def expand(self, *, maximum_cells: int = 4096) -> tuple[ICCoreTest, ...]:
        if maximum_cells < 1 or self.cell_count > maximum_cells:
            raise ValueError(
                f"IC core-test block expands to {self.cell_count} cells; "
                f"maximum is {maximum_cells}"
            )
        return tuple(
            ICCoreTest(scope, factor, horizon, delay, method, self.return_price_basis)
            for scope, factor, horizon, delay, method in product(
                self.product_scope_refs,
                self.factor_refs,
                self.horizons,
                self.entry_delay_bars,
                self.methods,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_ref": self.block_ref,
            "expansion": "explicit_cartesian",
            "cell_count": self.cell_count,
            **self.identity,
        }


def expand_core_test_blocks(
    blocks: Iterable[ICCoreTestBlock],
    *,
    maximum_cells_per_block: int = 4096,
) -> tuple[ICCoreTest, ...]:
    """Expand batches, remove duplicate cells, and return canonical order."""

    cells: dict[str, ICCoreTest] = {}
    for block in blocks:
        for cell in block.expand(maximum_cells=maximum_cells_per_block):
            cells[cell.core_test_ref] = cell
    return tuple(cells[key] for key in sorted(cells))


__all__ = ["ICCoreTestBlock", "expand_core_test_blocks"]
