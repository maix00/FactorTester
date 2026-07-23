"""HTTP boundary for point-in-time batch product-liquidity evidence."""

from __future__ import annotations

from flask import jsonify, request

from server.services.product_liquidity import product_liquidity_for_scope

from . import shared_bp


@shared_bp.post("/api/product-liquidity")
def product_liquidity():
    payload = request.get_json(silent=True) or {}
    products = _string_list(payload.get("products"))
    source = str(payload.get("source") or "").strip()
    as_of = str(payload.get("as_of") or "").strip()
    window_days = payload.get("window_days", 365)
    if not products:
        return jsonify(success=False, error="必须明确提供 products 范围"), 400
    if not source:
        return jsonify(success=False, error="必须明确提供 source"), 400
    if not as_of:
        return jsonify(success=False, error="必须明确提供 as_of 截止日"), 400
    if (
        not isinstance(window_days, int)
        or isinstance(window_days, bool)
        or window_days < 1
    ):
        return jsonify(success=False, error="window_days 必须为正整数"), 400
    try:
        evidence = product_liquidity_for_scope(
            product_names=products,
            source_name=source,
            as_of=as_of,
            window_days=window_days,
        )
    except LookupError as exc:
        return jsonify(success=False, error=str(exc)), 404
    except ValueError as exc:
        return jsonify(success=False, error=str(exc)), 400
    return jsonify(success=True, **evidence)


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
