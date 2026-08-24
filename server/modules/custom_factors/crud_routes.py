"""Routes for creating, updating, reading, and deleting factor sources."""
from __future__ import annotations

import re
from hashlib import sha256
from typing import cast

from flask import jsonify, request

from server.modules.custom_factors import cf_bp
from server.modules.custom_factors.catalog import (
    list_custom_factors,
    list_public_factors,
)
from server.modules.custom_factors.source_helpers import (
    assemble_factor_source,
    parse_class_meta,
    strip_factor_meta,
)
from server.services.factor_registry import (
    get_custom_factor_instance,
    invalidate_custom_factor_cache,
    invalidate_factor_family_cache,
)
from server.services.factor_workspace import commit_factor_source_change
from server.services.http_auth import login_required
from server.services.research_configurations import rename_factor_family_alias
from server.services.session_runtime import current_user
from tools.data.account_manage import (
    can_view_user_scope,
    get_account,
    is_super_admin_account,
)
from tools.data.factor_workspace.storage import (
    delete_factor_source,
    load_factor_source,
    load_public_factor_source,
    rename_factor_source,
    save_factor_source,
    save_public_factor_source,
)
from tools.data.sqlite.factor_source_store import (
    delete_factor_source as delete_factor_source_row,
)


def _current_user_is_super_admin() -> bool:
    return is_super_admin_account(get_account(current_user()))


def _username():
    """Return current username or None if not logged in."""
    u = current_user()
    if u is None:
        return None
    return u


def _commit_saved_source(username: str, operation: str, factor_id: str) -> str:
    try:
        result = commit_factor_source_change(
            username,
            f"factor: {operation} {factor_id}",
        )
    except Exception as error:
        raise RuntimeError(f"源码已保存，但 Git 提交失败：{error}") from error
    commit_sha = str(result.get("git_commit_sha") or "").strip()
    if not commit_sha:
        raise RuntimeError("源码已保存，但没有生成 Git 提交记录")
    return commit_sha


def _factor_family_ref(owner: str, family: str) -> str:
    identity = f"{owner}\x1f{family}"
    return f"factor-family:sha256:{sha256(identity.encode()).hexdigest()}"


@cf_bp.route('/api/create', methods=['POST'])
@login_required
def api_create_factor():
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    data = request.get_json(silent=True) or {}

    source_code = (data.get('source_code') or '').strip()
    if not source_code:
        return jsonify({'success': False, 'error': '源码不能为空'}), 400

    class_match = re.search(r'^\s*class\s+(\w+)\s*\(', source_code, re.MULTILINE)
    if not class_match:
        return jsonify({'success': False, 'error': '源码中未找到 class 定义'}), 400
    name = class_match.group(1)

    existing_names = {factor['name'] for factor in list_custom_factors(username)}
    if name in existing_names:
        return jsonify({'success': False, 'error': f'您已有同名自定义因子 "{name}"，请使用其他名称'}), 400

    factor_id = name
    chinese_name = (data.get('chinese_name') or '').strip()
    description = (data.get('description') or '').strip()
    category = (data.get('category') or '自编').strip()
    full_source = assemble_factor_source(source_code, chinese_name, description, category)

    save_factor_source(username, factor_id, full_source)
    try:
        git_commit_sha = _commit_saved_source(username, "create", factor_id)
    except RuntimeError as error:
        return jsonify({'success': False, 'error': str(error)}), 500

    return jsonify({
        'success': True,
        'factor': {
            'id': factor_id,
            'name': name,
            'chinese_name': chinese_name,
            'description': description,
            'category': category,
            'source_code': strip_factor_meta(full_source),
            'is_public': False,
            'git_commit_sha': git_commit_sha,
        }
    })


@cf_bp.route('/api/create-public', methods=['POST'])
@login_required
def api_create_public_factor():
    """Create one public FactorFamily source for a super administrator."""
    if not _current_user_is_super_admin():
        return jsonify({'success': False, 'error': '只有超级管理员可以新增公共因子家族'}), 403
    data = request.get_json(silent=True) or {}
    source_code = (data.get('source_code') or '').strip()
    if not source_code:
        return jsonify({'success': False, 'error': '源码不能为空'}), 400
    class_match = re.search(r'^\s*class\s+(\w+)\s*\(', source_code, re.MULTILINE)
    if not class_match:
        return jsonify({'success': False, 'error': '源码中未找到 class 定义'}), 400
    factor_id = class_match.group(1)
    if any(str(item.get('id') or '') == factor_id for item in list_public_factors()):
        return jsonify({'success': False, 'error': f'公共因子家族 "{factor_id}" 已存在'}), 400
    full_source = assemble_factor_source(
        source_code,
        (data.get('chinese_name') or '').strip(),
        (data.get('description') or '').strip(),
        (data.get('category') or '公共').strip(),
    )
    save_public_factor_source(factor_id, full_source)
    invalidate_factor_family_cache(factor_id)
    try:
        git_commit_sha = _commit_saved_source(_username(), "create public", factor_id)
    except RuntimeError as error:
        return jsonify({'success': False, 'error': str(error)}), 500
    meta = parse_class_meta(full_source)
    return jsonify({
        'success': True,
        'factor': {
            'id': factor_id,
            'name': factor_id,
            'chinese_name': meta.get('chinese_name', ''),
            'description': meta.get('description', ''),
            'category': meta.get('category', '公共'),
            'source_code': strip_factor_meta(full_source),
            'is_public': True,
            'type': 'public',
            'git_commit_sha': git_commit_sha,
        },
    })


@cf_bp.route('/api/update/<factor_id>', methods=['POST'])
@login_required
def api_update_factor(factor_id):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    existing_source = load_factor_source(username, factor_id)
    if existing_source is None:
        return jsonify({'success': False, 'error': '因子不存在'}), 404

    data = request.get_json(silent=True) or {}
    old_meta = parse_class_meta(existing_source)
    old_name = old_meta.get('name', '')

    source_code = (data.get('source_code') or '').strip()
    chinese_name = (data.get('chinese_name') or '').strip()
    description = (data.get('description') or '').strip()
    category = (data.get('category') or old_meta.get('category', '自编')).strip()
    new_name = old_name

    if source_code:
        class_match = re.search(r'^\s*class\s+(\w+)\s*\(', source_code, re.MULTILINE)
        new_name = class_match.group(1) if class_match else old_name
        if new_name != old_name:
            existing_names = {
                factor['name'] for factor in list_custom_factors(username)
                if factor['id'] != factor_id and factor['name'] != old_name
            }
            if new_name in existing_names:
                return jsonify({'success': False, 'error': f'您已有同名自定义因子 "{new_name}"'}), 400

        full_source = assemble_factor_source(
            source_code,
            chinese_name or old_meta.get('chinese_name', ''),
            description or old_meta.get('description', ''),
            category,
        )
    else:
        old_editor_source = strip_factor_meta(existing_source)
        full_source = assemble_factor_source(
            old_editor_source,
            chinese_name or old_meta.get('chinese_name', ''),
            description or old_meta.get('description', ''),
            category,
        )

    save_factor_source(username, factor_id, full_source)
    invalidate_custom_factor_cache(username, factor_id)
    if old_name and old_name != new_name:
        invalidate_factor_family_cache(old_name)
        rename_factor_family_alias(old_name, new_name)
        # 同步文件名：类名改了但 URL 里的 factor_id 还是旧名，
        # 先按新类名保存（上面已做），再删旧文件，保持文件名与类名一致。
        if rename_factor_source(username, factor_id, new_name):
            factor_id = new_name

    try:
        git_commit_sha = _commit_saved_source(username, "update", factor_id)
    except RuntimeError as error:
        return jsonify({'success': False, 'error': str(error)}), 500

    new_meta = parse_class_meta(full_source)
    return jsonify({
        'success': True,
        'factor': {
            'id': factor_id,
            'name': new_meta.get('name', old_name),
            'chinese_name': new_meta.get('chinese_name', ''),
            'description': new_meta.get('description', ''),
            'category': new_meta.get('category', '自编'),
            'source_code': strip_factor_meta(full_source),
            'is_public': False,
            'git_commit_sha': git_commit_sha,
        }
    })


@cf_bp.route('/api/update-public/<factor_id>', methods=['POST'])
@login_required
def api_update_public_factor(factor_id):
    if not _current_user_is_super_admin():
        return jsonify({'success': False, 'error': '只有超级管理员可以修改公共因子家族'}), 403

    existing_source = load_public_factor_source(factor_id)
    if existing_source is None:
        return jsonify({'success': False, 'error': '公共因子不存在'}), 404

    data = request.get_json(silent=True) or {}
    source_code = (data.get('source_code') or '').strip()
    if not source_code:
        return jsonify({'success': False, 'error': '源码不能为空'}), 400

    class_match = re.search(r'^\s*class\s+(\w+)\s*\(', source_code, re.MULTILINE)
    class_name = class_match.group(1) if class_match else ''
    if class_name != factor_id:
        return jsonify({'success': False, 'error': '公共因子家族暂不支持重命名，请保持 class 名与文件名一致'}), 400

    old_meta = parse_class_meta(existing_source)
    chinese_name = (data.get('chinese_name') or old_meta.get('chinese_name', '')).strip()
    description = (data.get('description') or old_meta.get('description', '')).strip()
    category = (data.get('category') or old_meta.get('category', '') or '公共').strip()
    full_source = assemble_factor_source(source_code, chinese_name, description, category)

    save_public_factor_source(factor_id, full_source)
    invalidate_factor_family_cache(factor_id)
    try:
        git_commit_sha = _commit_saved_source(_username(), "update public", factor_id)
    except RuntimeError as error:
        return jsonify({'success': False, 'error': str(error)}), 500

    new_meta = parse_class_meta(full_source)
    return jsonify({
        'success': True,
        'factor': {
            'id': factor_id,
            'name': new_meta.get('name', factor_id),
            'chinese_name': new_meta.get('chinese_name', ''),
            'description': new_meta.get('description', ''),
            'category': new_meta.get('category', '公共'),
            'source_code': strip_factor_meta(full_source),
            'is_public': True,
            'type': 'public',
            'git_commit_sha': git_commit_sha,
        }
    })


@cf_bp.route('/api/delete/<factor_id>', methods=['POST'])
@login_required
def api_delete_factor(factor_id):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    existing_source = load_factor_source(username, factor_id)
    if existing_source is None:
        return jsonify({'success': False, 'error': '因子不存在'}), 404

    old_meta = parse_class_meta(existing_source)
    old_name = old_meta.get('name', '')
    delete_factor_source(username, factor_id)

    invalidate_custom_factor_cache(username, factor_id)
    if old_name:
        invalidate_factor_family_cache(old_name)

    return jsonify({'success': True, 'message': f'因子 "{old_name}" 已删除'})


@cf_bp.route('/api/delete-public/<factor_id>', methods=['POST'])
@login_required
def api_delete_public_factor(factor_id):
    if not _current_user_is_super_admin():
        return jsonify({'success': False, 'error': '只有超级管理员可以删除公共因子家族'}), 403
    existing_source = load_public_factor_source(factor_id)
    if existing_source is None:
        return jsonify({'success': False, 'error': '公共因子家族不存在'}), 404
    delete_factor_source_row('public', '', factor_id)
    invalidate_factor_family_cache(factor_id)
    return jsonify({
        'success': True,
        'message': f'公共因子家族 "{factor_id}" 已删除',
    })


@cf_bp.route('/api/get/<factor_id>', methods=['GET'])
@login_required
def api_get_factor(factor_id):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    owner_username = cast(str, (request.args.get('owner_username') or username)).strip()
    if not can_view_user_scope(username, owner_username):
        return jsonify({'success': False, 'error': '无权查看该用户因子'}), 403
    source = load_factor_source(owner_username, factor_id)
    if source is None:
        return jsonify({'success': False, 'error': '因子不存在'}), 404

    meta = parse_class_meta(source)
    factor_family = get_custom_factor_instance(owner_username, factor_id)
    from server.modules.shared.param_meta import serialize_param_meta
    return jsonify({
        'success': True,
        'factor': {
            'id': factor_id,
            'name': meta.get('name', ''),
            'chinese_name': meta.get('chinese_name', ''),
            'description': meta.get('description', ''),
            'category': meta.get('category', '自编'),
            'source_code': strip_factor_meta(source),
            'is_public': False,
            'source': 'custom',
            'factor_kind': 'custom',
            'owner_username': owner_username,
            'owner_alias': owner_username,
            'factor_owner_ref': owner_username,
            'factor_family_alias': meta.get('name', '') or factor_id,
            'factor_family_ref': _factor_family_ref(
                owner_username, meta.get('name', '') or factor_id,
            ),
            'can_edit': owner_username == username,
            'math_expr': getattr(factor_family, 'math_expr', '') if factor_family is not None else '',
            'params': [serialize_param_meta(param) for param in factor_family.params] if factor_family is not None else [],
        }
    })
