"""Local historical FX rate lookup.

This is the data-source boundary for currency conversion. It currently provides
same-currency rates only. Cross-currency pairs return None until a real
historical FX source is wired here.
"""
from __future__ import annotations

from typing import Any


def _normalize(code: Any) -> str | None:
    value = str(code or "").strip().upper()
    return value or None


def get_fx_rate(from_currency: str, to_currency: str, _time_key: Any = None) -> float | None:
    from_code = _normalize(from_currency)
    to_code = _normalize(to_currency)
    if from_code and from_code == to_code:
        return 1.0
    return None
