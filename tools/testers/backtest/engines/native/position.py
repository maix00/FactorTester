"""Position primitives owned by native ledger accounting."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.data.types.data_money import DataMoney


@dataclass
class Lot:
    """One open-position batch.

    FIFO/LIFO/HIFO differ only in which lot is consumed first; the underlying
    lot schema is shared.
    """

    quantity: float | int
    entry_price: float
    multiplier: float
    is_today: bool | None = None


@dataclass
class ProductPosition:
    """One product's position record."""

    quantity: float | int = 0.0
    average_cost: float | None = None
    lots: "deque[Lot] | None" = None
    margin_reserved: "DataMoney | None" = None
    settlement_price: float | None = None


def apply_quantity_delta(entry: ProductPosition, delta: float) -> None:
    """Preserve entry.quantity's int/float type."""

    if isinstance(entry.quantity, int):
        entry.quantity += round(delta)
    else:
        entry.quantity += delta
