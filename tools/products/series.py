"""Typed view references for alternate series of one classified product."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProductSeriesRef:
    product: Any
    variant: str
    label: str
    backing_product_name: str
    adjusted: bool = False

    @property
    def key(self) -> str:
        return f"{getattr(self.product, 'name', self.product)}::{self.variant}"
