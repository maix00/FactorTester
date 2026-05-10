"""
Shared parameter-management routes (any test module can use):
  POST /add_params
  POST /delete_params
  POST /reorder_params
"""
from flask import request, jsonify
from server.services.factor_registry import get_factor_family_instance
from server.shared import _get_session_params, _save_session_params, _current_user
from . import shared_bp
from .param_config import normalize_param_row, param_value_display


def _build_factor_rows(ff, params_list):
    factors = ff.get_factors(params_list=params_list)
    rows = []
    for idx, (factor, row) in enumerate(zip(factors, params_list)):
        display_params = {}
        for p in ff.params:
            val = row.get(p.alias)
            display_params[p.alias] = param_value_display(p, val)
        rows.append({
            'index': idx,
            'factor_alias': factor.alias,
            'params': display_params,
        })
    return rows


@shared_bp.route('/add_params', methods=['POST'])
def add_params():
    data = request.get_json()
    factor_family_alias = data.get('factor_family_alias')
    params = data.get('params', {})
    try:
        ff = get_factor_family_instance(factor_family_alias, username=_current_user())
        new_params = normalize_param_row(ff, params)
        pl = _get_session_params(factor_family_alias, ff)
        if new_params not in pl:
            pl.append(new_params)
        _save_session_params(factor_family_alias, pl)
        added_display = {}
        for p in ff.params:
            val = new_params.get(p.alias)
            added_display[p.alias] = param_value_display(p, val)
        return jsonify({
            'success': True,
            'params_count': len(pl),
            'added_params': added_display,
            'factor_rows': _build_factor_rows(ff, pl),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@shared_bp.route('/delete_params', methods=['POST'])
def delete_params():
    data = request.get_json()
    factor_family_alias = data.get('factor_family_alias')
    factor_idx = int(data.get('factor_idx', -1))
    try:
        ff = get_factor_family_instance(factor_family_alias, username=_current_user())
        pl = _get_session_params(factor_family_alias, ff)
        if 0 <= factor_idx < len(pl):
            pl.pop(factor_idx)
        _save_session_params(factor_family_alias, pl)
        return jsonify({'success': True, 'factor_rows': _build_factor_rows(ff, pl)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@shared_bp.route('/reorder_params', methods=['POST'])
def reorder_params():
    data = request.get_json()
    factor_family_alias = data.get('factor_family_alias')
    from_idx = int(data.get('from_idx', -1))
    to_idx   = int(data.get('to_idx', -1))
    try:
        ff = get_factor_family_instance(factor_family_alias, username=_current_user())
        pl = _get_session_params(factor_family_alias, ff)
        if 0 <= from_idx < len(pl) and 0 <= to_idx < len(pl):
            param = pl.pop(from_idx)
            pl.insert(to_idx, param)
        _save_session_params(factor_family_alias, pl)
        return jsonify({'success': True, 'factor_rows': _build_factor_rows(ff, pl)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
