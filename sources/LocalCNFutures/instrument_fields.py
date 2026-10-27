"""LocalCNFutures product fields, using Nautilus names for native attributes.

Snapshot metadata is for inspection and initial construction, not evidence of
historical effective rules. No Nautilus runtime is imported for field display.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any
from tools.products.Futures import FuturesContract


def _contract_variety_code(product: Any) -> str:
    name = str(getattr(product, 'name', getattr(product, 'alias', product)))
    if '|' in name:
        parts = name.split('|')
        if len(parts) >= 3:
            return parts[2].upper()
    match = re.match(r'^([A-Za-z]+)', name)
    return match.group(1).upper() if match else ''


def _future_variety_code(product: Any) -> str:
    code = str(getattr(product, 'code', '') or '').upper()
    if code:
        return code
    alias = str(getattr(product, 'alias', getattr(product, 'name', '')))
    return alias.split('.')[0].upper() if alias else ''


def _fee_fields_from_row(row: Any, source: str) -> dict[str, Any]:
    import pandas as pd
    if row is None:
        return {}

    def num(key: str) -> Decimal | None:
        if key not in row:
            return None
        value = row.get(key)
        return Decimal(str(value)) if pd.notna(value) else None

    return {
        'trading_spec_source': source,
        'trading_spec_date': str(row.get('date', '')) if row.get('date', '') is not None else '',
        'open_fee_ratio': num('open_ratio'),
        'open_fee_fixed': num('open_fixed'),
        'close_fee_ratio': num('close_ratio'),
        'close_fee_fixed': num('close_fixed'),
        'close_today_fee_ratio': num('closetoday_ratio'),
        'close_today_fee_fixed': num('closetoday_fixed'),
        'long_margin_ratio': num('long_margin_ratio'),
        'long_margin_fixed': num('long_margin_fixed'),
        'short_margin_ratio': num('short_margin_ratio'),
        'short_margin_fixed': num('short_margin_fixed'),
        'price_increment': num('min_tick'),
        'multiplier': num('multiplier'),
        'min_quantity': num('min_trade_quantity'),
        'max_quantity': num('max_trade_quantity'),
    }


def _fill_missing_trading_spec_fields(product: Any, fields: dict[str, Any]) -> dict[str, Any]:
    """Fill missing Product trading-spec fields one by one."""
    mapping = {
        'open_fee_ratio': 'open_ratio',
        'open_fee_fixed': 'open_fixed',
        'close_fee_ratio': 'close_ratio',
        'close_fee_fixed': 'close_fixed',
        'close_today_fee_ratio': 'closetoday_ratio',
        'close_today_fee_fixed': 'closetoday_fixed',
        'long_margin_ratio': 'long_margin_ratio',
        'long_margin_fixed': 'long_margin_fixed',
        'short_margin_ratio': 'short_margin_ratio',
        'short_margin_fixed': 'short_margin_fixed',
        'price_increment': 'min_tick',
        'multiplier': 'multiplier',
        'min_quantity': 'min_trade_quantity',
        'max_quantity': 'max_trade_quantity',
    }
    getter = getattr(product, 'get_trading_spec_field', None)
    if not callable(getter):
        return fields
    filled = False
    for public_key, product_field in mapping.items():
        if fields.get(public_key) not in (None, ''):
            continue
        try:
            value = getter(product_field)
        except Exception:
            value = None
        if value not in (None, ''):
            fields[public_key] = Decimal(str(value))
            filled = True
    if filled:
        source = str(fields.get('trading_spec_source') or '').strip()
        fields['trading_spec_source'] = (
            f"{source}+openctp_fallback" if source else "openctp_fallback"
        )
    return fields


def _load_fields(product: Any) -> dict[str, Any]:
    """Return current/inferred CN futures trading specs for display.

    Futures uses the current variety-level OpenCTP row. FuturesContract first tries
    contract-level rows, then falls back to the current variety-level row.
    """
    try:
        from sources.LocalCNFutures.FeeData import get_contract_fee_row, load_latest
        import pandas as pd
    except Exception:
        return {}

    try:
        if isinstance(product, FuturesContract):
            contract_row = get_contract_fee_row(getattr(product, 'name', ''), allow_latest_fallback=True)
            if contract_row is not None:
                return _fill_missing_trading_spec_fields(
                    product,
                    _fee_fields_from_row(contract_row, 'current_contract_snapshot'),
                )
            variety = _contract_variety_code(product)
            source = 'current_variety_snapshot_fallback'
        else:
            variety = _future_variety_code(product)
            source = 'current_variety_snapshot'
        if not variety:
            return _fill_missing_trading_spec_fields(product, {})
        df = load_latest()
        if df.empty or 'variety_code' not in df.columns:
            return {}
        match = df[df['variety_code'].astype(str).str.upper() == variety]
        if match.empty:
            return _fill_missing_trading_spec_fields(product, {})
        return _fill_missing_trading_spec_fields(product, _fee_fields_from_row(match.iloc[0], source))
    except Exception:
        return {}


def instrument_fields(product: Any) -> dict[str, Any]:
    """Bundle-owned values shared by product detail and Instrument construction."""
    fields = _load_fields(product)
    if not fields:
        return fields
    long_rate, short_rate = fields.get("long_margin_ratio"), fields.get("short_margin_ratio")
    # A single proportional native rate cannot express asymmetric/fixed rules.
    unified = (long_rate is not None and long_rate == short_rate
               and not fields.get("long_margin_fixed")
               and not fields.get("short_margin_fixed"))
    fields["margin_init"] = long_rate if unified else None
    fields["margin_maint"] = long_rate if unified else None
    return fields
