"""TigerOpen subprocess bridge.

This file runs under the separately configured Tiger Python runtime. It accepts
one bounded JSON request on stdin and emits one redacted JSON object on stdout.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import time
from typing import Any


_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
_MAX_PRODUCTS = 20


def main() -> int:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("request_not_object")
        operation = str(request.get("operation") or "")
        if operation == "availability":
            response = _availability(request)
        elif operation == "catalog":
            response = _catalog(request)
        else:
            raise ValueError("operation_not_allowed")
    except ValueError as exc:
        response = {"status": "error", "error_code": str(exc)}
    except Exception:
        response = {"status": "error", "error_code": "tiger_request_failed"}
    sys.stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False))
    return 0


def _availability(request: dict[str, Any]) -> dict[str, Any]:
    products = request.get("products")
    if not isinstance(products, list) or not products or len(products) > _MAX_PRODUCTS:
        raise ValueError("invalid_product_scope")
    identifiers = []
    for product in products:
        if not isinstance(product, dict):
            raise ValueError("invalid_product_scope")
        identifier = str(product.get("identifier") or "")
        if not _IDENTIFIER.fullmatch(identifier):
            raise ValueError("invalid_provider_identifier")
        identifiers.append(identifier)

    quote = _quote_client()
    expanded = bool(request.get("expanded", False))
    with contextlib.redirect_stdout(sys.stderr):
        permissions = quote.get_quote_permission()
        briefs = quote.get_future_brief(identifiers, lang="en_US")

    quote_rows = []
    for row in _records(briefs):
        item = {
            "identifier": _text(row.get("identifier")),
            "latest_time": _integer(row.get("latest_time")),
        }
        if expanded:
            item["has_top_of_book"] = all(
                row.get(field) is not None
                for field in ("bid_price", "ask_price")
            )
        quote_rows.append(item)
    return {
        "status": "ok",
        "received_at_ms": int(time.time() * 1000),
        "permissions": [
            {
                "name": _text(item.get("name")),
                "expire_at": _integer(item.get("expire_at")),
            }
            for item in permissions
            if isinstance(item, dict) and item.get("name")
        ],
        "quotes": quote_rows,
    }


def _catalog(request: dict[str, Any]) -> dict[str, Any]:
    exchange = str(request.get("exchange") or "OSE").strip().upper()
    if exchange != "OSE":
        raise ValueError("exchange_not_allowed")
    quote = _quote_client()
    with contextlib.redirect_stdout(sys.stderr):
        frame = quote.get_future_contracts(exchange, lang="en_US")
    contracts = []
    for row in _records(frame):
        identifier = _text(row.get("contract_code"))
        if not _IDENTIFIER.fullmatch(identifier):
            continue
        contracts.append({
            "identifier": identifier,
            "product_code": _text(row.get("type")),
            "contract_month": _text(row.get("contract_month")),
            "currency": _text(row.get("currency")),
            "exchange": _text(row.get("exchange")),
            "last_trading_date": _text(row.get("last_trading_date")),
            "min_tick": _number(row.get("min_tick")),
            "multiplier": _number(row.get("multiplier")),
            "name": _text(row.get("name")),
            "timezone": _text(row.get("time_zone")),
            "tradable": bool(row.get("trade", False)),
        })
    return {"status": "ok", "exchange": exchange, "contracts": contracts}


def _quote_client():
    props_path = os.environ.get("TIGEROPEN_PROPS_PATH", "").strip()
    if not props_path or not os.path.isfile(props_path):
        raise ValueError("properties_not_configured")
    from tigeropen.quote.quote_client import QuoteClient
    from tigeropen.tiger_open_config import TigerOpenClientConfig

    config = TigerOpenClientConfig(props_path=props_path)
    return QuoteClient(config)


def _records(value: Any) -> list[dict[str, Any]]:
    if hasattr(value, "where") and hasattr(value, "notna"):
        value = value.where(value.notna(), None)
    if hasattr(value, "to_dict"):
        try:
            rows = value.to_dict(orient="records")
            return [dict(row) for row in rows]
        except TypeError:
            pass
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
