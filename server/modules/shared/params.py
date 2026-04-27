"""
Shared parameter-management routes (any test module can use):
  POST /add_params
  POST /delete_params
  POST /reorder_params
"""
from flask import request, jsonify
from server.shared import get_factor_family_instance, _get_session_params, _save_session_params
from . import shared_bp


@shared_bp.route('/add_params', methods=['POST'])
def add_params():
    data = request.get_json()
    factor_family_alias = data.get('factor_family_alias')
    params = data.get('params', {})
    try:
        ff = get_factor_family_instance(factor_family_alias)
        ff._check_in_space(**params)
        new_params = {
            p.alias: p.rectify_value(params[p.alias]) if p.alias in params else p.default_value
            for p in ff.params
        }
        pl = _get_session_params(factor_family_alias, ff)
        if new_params not in pl:
            pl.append(new_params)
        _save_session_params(factor_family_alias, pl)
        added_display = {}
        for p in ff.params:
            val = new_params.get(p.alias)
            if val is not None and hasattr(p, 'get_value_alias'):
                try:
                    added_display[p.alias] = p.get_value_alias(val)
                except Exception:
                    added_display[p.alias] = str(val)
            else:
                added_display[p.alias] = str(val) if val is not None else ''
        return jsonify({'success': True, 'params_count': len(pl), 'added_params': added_display})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@shared_bp.route('/delete_params', methods=['POST'])
def delete_params():
    data = request.get_json()
    factor_family_alias = data.get('factor_family_alias')
    factor_idx = int(data.get('factor_idx', -1))
    try:
        ff = get_factor_family_instance(factor_family_alias)
        pl = _get_session_params(factor_family_alias, ff)
        if 0 <= factor_idx < len(pl):
            pl.pop(factor_idx)
        _save_session_params(factor_family_alias, pl)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@shared_bp.route('/reorder_params', methods=['POST'])
def reorder_params():
    data = request.get_json()
    factor_family_alias = data.get('factor_family_alias')
    from_idx = int(data.get('from_idx', -1))
    to_idx   = int(data.get('to_idx', -1))
    try:
        ff = get_factor_family_instance(factor_family_alias)
        pl = _get_session_params(factor_family_alias, ff)
        if 0 <= from_idx < len(pl) and 0 <= to_idx < len(pl):
            param = pl.pop(from_idx)
            pl.insert(to_idx, param)
        _save_session_params(factor_family_alias, pl)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
