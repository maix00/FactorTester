"""One deterministic cell in the IC core-test matrix."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


IC_CORE_AXES = (
    "product_scope_ref",
    "factor_ref",
    "horizon",
    "entry_delay_bars",
    "method",
)

IC_CORE_OUTPUT_KINDS = (
    "ic_series",
    "ic_statistics",
    "factor_values",
    "forward_returns",
    "eligibility",
)


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty text")
    return text


@dataclass(frozen=True, slots=True)
class ICCoreTest:
    product_scope_ref: str
    factor_ref: str
    horizon: str
    entry_delay_bars: int
    method: str
    return_price_basis: str

    def __post_init__(self) -> None:
        for name in (
            "product_scope_ref",
            "factor_ref",
            "horizon",
            "method",
            "return_price_basis",
        ):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        if isinstance(self.entry_delay_bars, bool):
            raise ValueError("entry_delay_bars must be a non-negative integer")
        try:
            delay = int(self.entry_delay_bars)
        except (TypeError, ValueError) as exc:
            raise ValueError("entry_delay_bars must be a non-negative integer") from exc
        if delay < 0 or delay != self.entry_delay_bars:
            raise ValueError("entry_delay_bars must be a non-negative integer")
        object.__setattr__(self, "entry_delay_bars", delay)

    @property
    def core_test_ref(self) -> str:
        payload = json.dumps(
            self.identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()
        return f"ic-core:v1:{hashlib.sha256(payload).hexdigest()}"

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "product_scope_ref": self.product_scope_ref,
            "factor_ref": self.factor_ref,
            "horizon": self.horizon,
            "entry_delay_bars": self.entry_delay_bars,
            "method": self.method,
            "return_price_basis": self.return_price_basis,
        }

    @property
    def output_kinds(self) -> frozenset[str]:
        return frozenset(IC_CORE_OUTPUT_KINDS)

    def axis_value(self, name: str) -> Any:
        if name not in IC_CORE_AXES:
            raise ValueError(f"unknown core-test axis: {name}")
        return getattr(self, name)

    def to_dict(self) -> dict[str, Any]:
        return {"core_test_ref": self.core_test_ref, **self.identity}
