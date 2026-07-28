"""HTTP boundary for compact market-data availability inspection."""

from __future__ import annotations

from flask import jsonify, request

from server.services.data_availability import availability_for_scope

from . import shared_bp


@shared_bp.post("/api/data-availability")
def data_availability():
    payload = request.get_json(silent=True) or {}
    products = _string_list(payload.get("products"))
    sources = _string_list(payload.get("sources"))
    if not products:
        return jsonify(success=False, error="必须明确提供 products 范围"), 400
    if not sources:
        return jsonify(success=False, error="必须明确提供 sources 范围"), 400
    try:
        profile = availability_for_scope(
            product_names=products,
            source_names=sources,
            frequency_names=_string_list(payload.get("frequencies")),
            probe=bool(payload.get("probe", False)),
            expanded=bool(payload.get("expanded", False)),
            required_fields=_string_list(payload.get("fields")),
            include_field_catalog=bool(payload.get("include_field_catalog", False)),
            include_historical_fields=bool(payload.get("include_historical_fields", False)),
        )
    except LookupError as exc:
        return jsonify(success=False, error=str(exc)), 404
    except ValueError as exc:
        return jsonify(success=False, error=str(exc)), 400
    return jsonify(success=True, **profile)


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
