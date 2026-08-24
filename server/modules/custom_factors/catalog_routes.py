"""Routes for custom-factor catalog pages and read-only factor metadata."""
from __future__ import annotations

from hashlib import sha256
from typing import Any, cast

from flask import jsonify, request

from server.modules.custom_factors import cf_bp
from server.modules.custom_factors.catalog import (
    _load_factor_family_from_source,
    get_public_factor_detail,
    list_custom_factors,
    list_public_factors,
    list_visible_custom_factors,
)
from server.modules.custom_factors.source_helpers import strip_factor_meta
from server.modules.shared.param_meta import serialize_param_meta
from server.services.http_auth import login_required
from server.services.session_runtime import current_user
from tools.data.account_manage import can_view_user_scope, get_account, load_accounts
from tools.data.factor_workspace.storage import (
    load_factor_source,
    load_public_factor_source,
)
from tools.data.factor_workspace.versions import (
    list_factor_source_versions,
    load_factor_source_version,
)


@cf_bp.route('/api/list', methods=['GET'])
@login_required
def api_list_factors():
    username = cast(str, current_user())
    public = list_public_factors()
    include_subordinates = request.args.get('include_subordinates') == '1'
    if include_subordinates:
        custom = list_visible_custom_factors(username)
    else:
        custom = list_custom_factors(username)
        account = get_account(username) or {}
        for factor in custom:
            factor['owner_username'] = username
            factor['owner_alias'] = '我'
            factor['owner_organization_id'] = account.get('organization_id') or ''
            factor['owner_organization_name'] = account.get('organization_name') or ''
            factor['can_edit'] = True

    is_admin = False
    if username:
        for account in load_accounts():
            if account.get('username') == username and account.get('is_admin'):
                is_admin = True
                break
    return jsonify({
        'success': True,
        'public_factors': public,
        'custom_factors': custom,
        'current_username': username,
        'is_admin': is_admin,
    })


@cf_bp.route('/api/public-factor/<factor_name>', methods=['GET'])
@login_required
def api_public_factor_detail(factor_name):
    detail = get_public_factor_detail(factor_name)
    if detail is None:
        return jsonify({'success': False, 'error': f'公共因子 "{factor_name}" 不存在'}), 404
    return jsonify({'success': True, 'factor': detail})


def _source_kind(value: str) -> str:
    kind = str(value or '').strip().lower()
    if kind not in {'custom', 'public'}:
        raise ValueError('源码类型无效')
    return kind


def _factor_family_ref(owner: str, family: str) -> str:
    """Build the same stable family ref used by client-library projections."""
    identity = f"{owner}\x1f{family}"
    return f"factor-family:sha256:{sha256(identity.encode()).hexdigest()}"


def _source_detail(source_code: str, module_name: str) -> dict[str, Any]:
    factor_cls, _ = _load_factor_family_from_source(source_code, module_name)
    if factor_cls is None:
        return {
            'source_code': strip_factor_meta(source_code),
            'math_expr': '',
            'chinese_name': '',
            'description': '',
            'params': [],
        }
    family = factor_cls()
    return {
        'source_code': strip_factor_meta(source_code),
        'math_expr': getattr(family, 'math_expr', '') or '',
        'chinese_name': getattr(family, 'desc', '') or '',
        'description': getattr(family, 'description', '') or '',
        'params': [serialize_param_meta(param) for param in family.params],
    }


def _source_context(source_kind: str, factor_id: str, username: str) -> tuple[str, str, str]:
    owner = str(request.args.get('owner_username') or '').strip()
    if source_kind == 'custom':
        owner = owner or username
        if not can_view_user_scope(username, owner):
            raise PermissionError('无权查看该用户因子源码')
        source_code = load_factor_source(owner, factor_id) or ''
        if not source_code:
            raise FileNotFoundError('因子源码不存在')
        return owner, source_code, owner
    source_code = load_public_factor_source(factor_id) or ''
    if not source_code:
        raise FileNotFoundError('公共因子源码不存在')
    return '__public_jobs__', source_code, str(
        request.args.get('workspace_username') or '',
    ).strip()


@cf_bp.route('/api/source-versions/<source_kind>/<factor_id>', methods=['GET'])
@login_required
def api_source_versions(source_kind, factor_id):
    username = cast(str, current_user())
    try:
        kind = _source_kind(source_kind)
        owner, source_code, workspace_username = _source_context(
            kind, factor_id, username,
        )
        value = list_factor_source_versions(
            source_kind=kind,
            owner_username=owner if kind == 'custom' else '',
            factor_id=factor_id,
            current_source=source_code,
            workspace_username=workspace_username,
            limit=request.args.get('limit', 100),
        )
        return jsonify({
            'success': True,
            **value,
            'source_kind': kind,
            'factor_id': factor_id,
            'factor_owner_ref': owner,
            'factor_family_ref': _factor_family_ref(
                owner, factor_id,
            ),
        })
    except PermissionError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 403
    except (FileNotFoundError, ValueError) as exc:
        return jsonify({'success': False, 'error': str(exc)}), 404


@cf_bp.route(
    '/api/source-versions/<source_kind>/<factor_id>/<version>',
    methods=['GET'],
)
@login_required
def api_source_version(source_kind, factor_id, version):
    username = cast(str, current_user())
    try:
        kind = _source_kind(source_kind)
        owner, source_code, workspace_username = _source_context(
            kind, factor_id, username,
        )
        value = load_factor_source_version(
            source_kind=kind,
            owner_username=owner if kind == 'custom' else '',
            factor_id=factor_id,
            current_source=source_code,
            commit=version,
            workspace_username=workspace_username,
        )
        detail = _source_detail(source_code=value['source_code'], module_name=factor_id)
        return jsonify({
            'success': True,
            **value,
            **detail,
            'source_kind': kind,
            'factor_id': factor_id,
            'factor_owner_ref': owner,
            'factor_family_ref': _factor_family_ref(owner, factor_id),
        })
    except PermissionError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 403
    except (FileNotFoundError, ValueError) as exc:
        return jsonify({'success': False, 'error': str(exc)}), 404
