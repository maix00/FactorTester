"""Single-factor-test setting snapshot template routes."""

from flask import jsonify, request

from server.modules.templates import templates_bp
from server.modules.templates.common import SINGLE_FACTOR_SETTING_TEMPLATE_KIND, load_template_list, new_template_id, save_template_list
from server.modules.templates.summary import build_snapshot_summary
from server.services.http_auth import login_required
from server.services.runtime_state import get_user_file_lock, require_user


@templates_bp.route('/api/single_factor_setting_templates/<factor_family_alias>', methods=['GET'])
@login_required
def list_single_factor_setting_templates(factor_family_alias):
    username = require_user()
    with get_user_file_lock(username):
        templates = load_template_list(username, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, scope_key=factor_family_alias)
    result = []
    for template in templates:
        snapshot = template.get('snapshot', {})
        result.append({
            'id': template['id'],
            'name': template['name'],
            'ff_alias': template.get('ff_alias', ''),
            'factor_family_alias': factor_family_alias,
            'summary': build_snapshot_summary(snapshot),
        })
    return jsonify({'success': True, 'templates': result})


@templates_bp.route('/api/single_factor_setting_templates/<factor_family_alias>', methods=['POST'])
@login_required
def save_single_factor_setting_template(factor_family_alias):
    data = request.get_json()
    name = (data.get('name') or '').strip()
    ff_alias = (data.get('ff_alias') or '').strip()
    snapshot = data.get('snapshot', {})
    if not name:
        return jsonify({'success': False, 'error': '模板名称不能为空'})
    if not ff_alias:
        return jsonify({'success': False, 'error': '因子家族不能为空'})
    username = require_user()
    with get_user_file_lock(username):
        templates = load_template_list(username, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, scope_key=factor_family_alias)
        template_id = new_template_id()
        templates.append({
            'id': template_id,
            'name': name,
            'ff_alias': ff_alias,
            'snapshot': snapshot,
        })
        save_template_list(username, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, templates, scope_key=factor_family_alias)
    return jsonify({'success': True, 'id': template_id})


@templates_bp.route('/api/single_factor_setting_templates/<factor_family_alias>/<tpl_id>', methods=['GET'])
@login_required
def get_single_factor_setting_template(factor_family_alias, tpl_id):
    username = require_user()
    with get_user_file_lock(username):
        templates = load_template_list(username, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, scope_key=factor_family_alias)
    template = next((t for t in templates if t['id'] == tpl_id), None)
    if not template:
        return jsonify({'success': False, 'error': '模板不存在'}), 404
    return jsonify({'success': True, 'template': template})


@templates_bp.route('/api/single_factor_setting_templates/<factor_family_alias>/<tpl_id>', methods=['PUT'])
@login_required
def update_single_factor_setting_template(factor_family_alias, tpl_id):
    data = request.get_json()
    username = require_user()
    with get_user_file_lock(username):
        templates = load_template_list(username, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, scope_key=factor_family_alias)
        template = next((t for t in templates if t['id'] == tpl_id), None)
        if not template:
            return jsonify({'success': False, 'error': '模板不存在'}), 404
        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return jsonify({'success': False, 'error': '模板名称不能为空'})
            template['name'] = name
        if 'snapshot' in data:
            template['snapshot'] = data['snapshot']
        save_template_list(username, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, templates, scope_key=factor_family_alias)
    return jsonify({'success': True})


@templates_bp.route('/api/single_factor_setting_templates/<factor_family_alias>/<tpl_id>', methods=['DELETE'])
@login_required
def delete_single_factor_setting_template(factor_family_alias, tpl_id):
    username = require_user()
    with get_user_file_lock(username):
        templates = load_template_list(username, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, scope_key=factor_family_alias)
        before = len(templates)
        templates = [t for t in templates if t['id'] != tpl_id]
        if len(templates) == before:
            return jsonify({'success': False, 'error': '模板不存在'}), 404
        save_template_list(username, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, templates, scope_key=factor_family_alias)
    return jsonify({'success': True})


@templates_bp.route('/api/single_factor_setting_templates/<factor_family_alias>/factors', methods=['GET'])
@login_required
def list_single_factor_setting_template_factors(factor_family_alias):
    """List factors covered by setting snapshots for a single-factor FactorFamily."""
    username = require_user()
    with get_user_file_lock(username):
        templates = load_template_list(username, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, scope_key=factor_family_alias)

    ff_aliases = {
        template.get('ff_alias', '').strip()
        for template in templates
        if template.get('ff_alias', '').strip()
    }

    from server.modules.custom_factors.catalog import list_custom_factors, list_public_factors
    public_factors = {factor['id']: factor for factor in list_public_factors()}
    custom_factors = {factor['id']: factor for factor in list_custom_factors(username)}

    groups: dict[str, list] = {}
    for alias in sorted(ff_aliases):
        factor_info = None
        source = None
        if alias in public_factors:
            factor_info = public_factors[alias]
            source = 'public'
        elif alias in custom_factors:
            factor_info = custom_factors[alias]
            source = 'custom'

        if factor_info:
            family = factor_info.get('factor_family', 'FactorFamily')
            description = factor_info.get('description', '')
            entry = {
                'id': alias,
                'name': factor_info.get('name', alias),
                'chinese_name': factor_info.get('chinese_name', ''),
                'category': factor_info.get('category', ''),
                'source': source,
                'updated_at': factor_info.get('updated_at', ''),
                'params_count': len(factor_info.get('params', [])),
                'description': description[:120] + ('...' if len(description) > 120 else ''),
            }
        else:
            family = 'FactorFamily'
            entry = {
                'id': alias,
                'name': alias,
                'chinese_name': '',
                'category': '',
                'source': 'unknown',
                'updated_at': '',
                'params_count': 0,
                'description': '',
            }

        groups.setdefault(family, []).append(entry)

    grouped = [{'family': key, 'factors': value} for key, value in sorted(groups.items())]

    return jsonify({
        'success': True,
        'factor_family_alias': factor_family_alias,
        'groups': grouped,
        'total_factors': sum(len(group['factors']) for group in grouped),
    })
