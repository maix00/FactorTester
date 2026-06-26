"""
Shared parameter-management routes (any test module can use):
  POST /add_factor_by_params
"""
from flask import request
from server.services.factor_registry import get_factor_family_instance, get_page_factor, set_page_factor
from server.services.session_runtime import current_user
from . import shared_bp
from server.services.api_response import api_ok, route_guard
from .param_config import build_factor_rows, normalize_param_row, param_value_display


@shared_bp.route('/add_factor_by_params', methods=['POST'])
@route_guard
def add_factor_by_params():
    data = request.get_json()
    factor_family_alias = data.get('factor_family_alias')
    params = data.get('params', {})
    page_uuid = str(data.get('page_uuid') or '')
    ff = get_factor_family_instance(factor_family_alias, username=current_user())
    new_params = normalize_param_row(ff, params)
    new_alias = ff.get_alias(**new_params)

    # Factor is the single source of truth, stored in page_factors.
    # Check if already exists — if not, create via FactorFamily.get_factor().
    existing = get_page_factor(page_uuid, new_alias) if page_uuid else None
    existed = existing is not None
    if not existed and page_uuid:
        ff.get_factor(**new_params, page_uuid=page_uuid)

    added_display = {}
    for p in ff.params:
        val = new_params.get(p.alias)
        added_display[p.alias] = param_value_display(p, val)

    # Collect all current factors for this page+family to build factor_rows
    factors_for_page = {}
    if page_uuid:
        from server.services.factor_registry import page_factors
        page_dict = page_factors.get(page_uuid, {})
        factors_for_page = {
            alias: f for alias, f in page_dict.items()
            if getattr(f, 'family', None) and getattr(f.family, 'alias', None) == factor_family_alias
        }

    factor_rows = []
    for alias, factor in factors_for_page.items():
        display_params = {}
        for p in ff.params:
            val = getattr(factor, p.alias, None)
            display_params[p.alias] = param_value_display(p, val)
        factor_rows.append({
            'index': len(factor_rows),
            'factor_alias': alias,
            'params': display_params,
        })

    return api_ok({
        'factor_alias': new_alias,
        'existed': existed,
        'added_params': added_display,
        'factor_rows': factor_rows,
    })


# ── Removed routes (params are now page-scoped, not session-scoped) ──
# /delete_factor_by_params  — frontend manages candidate list locally
# /reorder_params            — frontend manages order locally
# /replace_params            — replaced by per-candidate add_factor_by_params

