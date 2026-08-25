"""One typed IC core-test authoring request."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from ..horizon import ICHorizonPolicy
from .normalization import entry_delays, required_texts
from tools.factors.formula_identity import is_factor_reference


def _is_frozen_factor_ref(value: str) -> bool:
    return is_factor_reference(value)


@dataclass(frozen=True, slots=True)
class ICCoreTestRequest:
    product_scope_refs: tuple[str, ...]
    factor_refs: tuple[str, ...]
    horizon: ICHorizonPolicy | Mapping[str, Any]
    entry_delay_bars: tuple[int, ...]
    methods: tuple[str, ...]
    return_price_basis: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "product_scope_refs",
            required_texts(self.product_scope_refs, "product_scope_refs"),
        )
        factors = required_texts(self.factor_refs, "factor_refs")
        if any(not _is_frozen_factor_ref(value) for value in factors):
            raise ValueError("factor_refs must contain frozen factor identities")
        object.__setattr__(self, "factor_refs", factors)
        policy = self.horizon
        if not isinstance(policy, ICHorizonPolicy):
            policy = ICHorizonPolicy.from_value(policy)
        object.__setattr__(self, "horizon", policy)
        object.__setattr__(
            self, "entry_delay_bars", entry_delays(self.entry_delay_bars),
        )
        methods = required_texts(self.methods, "methods")
        if not set(methods) <= {"rank", "pearson"}:
            raise ValueError("methods must contain rank or pearson")
        object.__setattr__(self, "methods", methods)
        basis = str(self.return_price_basis or "").strip()
        if not basis:
            raise ValueError("return_price_basis must be non-empty text")
        object.__setattr__(self, "return_price_basis", basis)

    @property
    def request_ref(self) -> str:
        payload = json.dumps(
            self.identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return f"ic-core-request:v1:{hashlib.sha256(payload).hexdigest()}"

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "product_scope_refs": list(self.product_scope_refs),
            "factor_refs": list(self.factor_refs),
            "horizon": self.horizon.to_dict(),
            "entry_delay_bars": list(self.entry_delay_bars),
            "methods": list(self.methods),
            "return_price_basis": self.return_price_basis,
        }

    def to_dict(self, *, include_ref: bool = True) -> dict[str, Any]:
        prefix = {"request_ref": self.request_ref} if include_ref else {}
        return {**prefix, **self.identity}

    @classmethod
    def from_authoring_dict(cls, value: Any) -> ICCoreTestRequest:
        item = cls._parse(value)
        supplied_ref = str(value.get("request_ref") or "").strip()
        if supplied_ref and supplied_ref != item.request_ref:
            raise ValueError("request_ref does not match the core request")
        return item

    @classmethod
    def from_frozen_dict(cls, value: Any) -> ICCoreTestRequest:
        item = cls._parse(value)
        if str(value.get("request_ref") or "").strip() != item.request_ref:
            raise ValueError("request_ref does not match the core request")
        return item

    @classmethod
    def _parse(cls, value: Any) -> ICCoreTestRequest:
        if not isinstance(value, dict):
            raise ValueError("IC core-test request must be an object")
        return cls(
            tuple(value.get("product_scope_refs") or ()),
            tuple(value.get("factor_refs") or ()),
            ICHorizonPolicy.from_dict(value.get("horizon")),
            tuple(value.get("entry_delay_bars") or ()),
            tuple(value.get("methods") or ()),
            value.get("return_price_basis"),
        )


__all__ = ["ICCoreTestRequest"]
