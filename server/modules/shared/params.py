"""
Shared parameter-management routes (any test module can use):
  POST /add_factor_by_params
  POST /delete_factor_by_params
  POST /reorder_params
"""
from flask import request
from server.services.factor_registry import get_factor_family_instance
from server.services.session_runtime import current_user, get_session_params, save_session_params
from . import shared_bp
from server.services.api_response import api_ok, route_guard
from .param_config import build_factor_rows, normalize_param_row, param_value_display


@shared_bp.route('/add_factor_by_params', methods=['POST'])
@route_guard
def add_factor_by_params():
    data = request.get_json()
    factor_family_alias = data.get('factor_family_alias')
    params = data.get('params', {})
    ff = get_factor_family_instance(factor_family_alias, username=current_user())
    new_params = normalize_param_row(ff, params)
    new_alias = ff.get_alias(**new_params)
    pl = get_session_params(factor_family_alias, ff)
    # Dedup by factor alias (same as /replace_params), not by dict equality
    existing_aliases = {ff.get_alias(**p) for p in pl}
    if new_alias not in existing_aliases:
        pl.append(new_params)
    save_session_params(factor_family_alias, pl)
    added_display = {}
    for p in ff.params:
        val = new_params.get(p.alias)
        added_display[p.alias] = param_value_display(p, val)
    return api_ok({
        'params_count': len(pl),
        'added_params': added_display,
        'factor_rows': build_factor_rows(ff, pl),
    })


@shared_bp.route('/delete_factor_by_params', methods=['POST'])
@route_guard
def delete_factor_by_params():
    data = request.get_json()
    factor_family_alias = data.get('factor_family_alias')
    factor_idx = int(data.get('factor_idx', -1))
    ff = get_factor_family_instance(factor_family_alias, username=current_user())
    pl = get_session_params(factor_family_alias, ff)
    if 0 <= factor_idx < len(pl):
        pl.pop(factor_idx)
    save_session_params(factor_family_alias, pl)
    return api_ok({'factor_rows': build_factor_rows(ff, pl)})


@shared_bp.route('/reorder_params', methods=['POST'])
@route_guard
def reorder_params():
    data = request.get_json()
    factor_family_alias = data.get('factor_family_alias')
    from_idx = int(data.get('from_idx', -1))
    to_idx   = int(data.get('to_idx', -1))
    ff = get_factor_family_instance(factor_family_alias, username=current_user())
    pl = get_session_params(factor_family_alias, ff)
    if 0 <= from_idx < len(pl) and 0 <= to_idx < len(pl):
        param = pl.pop(from_idx)
        pl.insert(to_idx, param)
    save_session_params(factor_family_alias, pl)
    return api_ok({'factor_rows': build_factor_rows(ff, pl)})
