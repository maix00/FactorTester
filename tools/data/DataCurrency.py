"""Currency metadata and conversion helpers.

This module owns currency normalization and historical FX lookup boundaries.
The concrete data source lives under ``sources/FXRates``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np


FxRateProvider = Callable[[str, str, Any], float | None]


def normalize_currency(value: Any, default: str = "CNY") -> str:
    code = str(value or default).strip().upper()
    return code or default


def normalize_optional_currency(value: Any) -> str | None:
    code = str(value or "").strip().upper()
    return code or None


def resolve_product_currency(product_ref: Any, *, default: str | None = None) -> str | None:
    direct = normalize_optional_currency(getattr(product_ref, "currency", None))
    if direct:
        return direct
    try:
        from tools.products import lookup_contract_product
        resolved = lookup_contract_product(str(product_ref), [])
        resolved_currency = normalize_optional_currency(getattr(resolved, "currency", None))
        if resolved_currency:
            return resolved_currency
    except Exception:
        pass
    return normalize_optional_currency(default) if default is not None else None


def require_product_currency_vector(
    product_refs: list[Any] | tuple[Any, ...],
    *,
    explicit: Any = None,
    default: str | None = None,
) -> np.ndarray:
    if explicit is not None:
        arr = np.asarray(explicit, dtype=object).reshape(len(product_refs))
        normalized = [normalize_optional_currency(c) for c in arr]
        missing = [str(ref) for ref, currency in zip(product_refs, normalized) if not currency]
        if missing:
            raise ValueError(f"产品缺少 currency 字段，无法进行分组交易: {missing[:5]}")
        return np.asarray(normalized, dtype=object)

    currencies = [resolve_product_currency(ref, default=default) for ref in product_refs]
    missing = [str(ref) for ref, currency in zip(product_refs, currencies) if not currency]
    if missing:
        raise ValueError(f"产品缺少 currency 字段，无法进行分组交易: {missing[:5]}")
    return np.asarray(currencies, dtype=object)


def default_fx_rate_provider(from_currency: str, to_currency: str, _time_key: Any = None) -> float | None:
    from sources.FXRates import get_fx_rate
    return get_fx_rate(from_currency, to_currency, _time_key)


@dataclass(frozen=True)
class CurrencyConversionContext:
    base_currency: str = "CNY"
    conversion_fee_rate: float = 0.0
    rate_provider: FxRateProvider = default_fx_rate_provider

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_currency", normalize_currency(self.base_currency))
        object.__setattr__(self, "conversion_fee_rate", max(0.0, float(self.conversion_fee_rate or 0.0)))

    def rate_to_base(self, currency: Any, time_key: Any = None) -> float:
        currency_code = normalize_optional_currency(currency)
        if not currency_code:
            raise ValueError("缺少交易品种 currency，无法换算到基础货币")
        if currency_code == self.base_currency:
            return 1.0
        rate = self.rate_provider(currency_code, self.base_currency, time_key)
        if rate is None or not np.isfinite(float(rate)) or float(rate) <= 0:
            raise ValueError(
                f"Missing FX rate {currency_code}->{self.base_currency}"
                + (f" at {time_key}" if time_key is not None else "")
            )
        return float(rate)

    def to_base(self, amount: Any, currency: Any, time_key: Any = None, *, applies_fee: bool = False) -> np.ndarray:
        currency_code = normalize_optional_currency(currency)
        if not currency_code:
            raise ValueError("缺少交易品种 currency，无法换算到基础货币")
        converted = np.asarray(amount, dtype=float) * self.rate_to_base(currency_code, time_key)
        if applies_fee and currency_code != self.base_currency:
            converted = converted * (1.0 + self.conversion_fee_rate)
        return converted
