"""Shared helpers for factor routes (page-uuid auth, page-factors lookup, tester resolution)."""
from __future__ import annotations

from typing import Any

from flask import jsonify

import server.services.page_runtime as page_runtime
from server.services.session_runtime import current_user
from server.modules.shared.factor_tester_runtime import create_factor_tester_for_product_path_selection
from server.modules.single_factor_test.ic_params import run_window_datetimes


def request_page_uuid(data: dict) -> tuple[str | None, Any | None]:
    page_uuid = str(data.get('page_uuid') or '').strip()
    if not page_uuid:
        return None, (jsonify({'error': '缺少 page_uuid'}), 400)
    if page_runtime.get_page_owner(page_uuid) != current_user():
        return None, (jsonify({'error': 'page_uuid 不属于当前用户'}), 403)
    return page_uuid, None


def get_page_factors_for_family(page_uuid: str, factor_family) -> list:
    """Populate and return factors from page_factors for the given family+page.

    Factors are the single source of truth in page_factors.
    """
    from server.services.factor_registry import page_factors
    page_dict = page_factors.get(str(page_uuid), {})
    family_alias = getattr(factor_family, 'alias', '')
    factors = [
        f for alias, f in page_dict.items()
        if getattr(getattr(f, 'family', None), 'alias', None) == family_alias
    ]
    factor_family.factors = factors
    return factors


def request_product_path_selection_id(data: dict[str, Any]) -> str:
    raw = data.get("product_path_selection")
    if isinstance(raw, dict):
        selection_id = (
            raw.get("product_path_selection_id")
            or raw.get("selection_id")
            or raw.get("id")
            or data.get("product_path_selection_id")
        )
    else:
        selection_id = data.get("product_path_selection_id")
    selection_id = str(selection_id or "").strip()
    if not selection_id:
        raise AssertionError("缺少 product_path_selection_id")
    return selection_id


def get_or_create_selection_tester(data: dict[str, Any], *, page_uuid: str, caller: str):
    selection_id = request_product_path_selection_id(data)
    try:
        return page_runtime.get_page_object(
            page_runtime.FACTOR_TESTER, selection_id, caller=caller, page_uuid=page_uuid
        )
    except AssertionError:
        raw_settings = data.get("settings")
        settings = raw_settings if isinstance(raw_settings, dict) else data
        start_dt, end_dt = run_window_datetimes(settings)
        return create_factor_tester_for_product_path_selection(
            data,
            selection_id,
            page_uuid=page_uuid,
            start_dt=start_dt,
            end_dt=end_dt,
        )
