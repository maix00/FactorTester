"""Routes for custom-factor catalog pages and read-only factor metadata."""
from __future__ import annotations

from typing import cast

from flask import jsonify, request

from server.modules.custom_factors import factor_library_internal_bp
from server.modules.custom_factors.catalog import (
    get_public_factor_detail,
    list_custom_factors,
    list_public_factors,
    list_visible_custom_factors,
)
from server.services.factor_source_catalog import FactorSourceCatalog
from server.services.http_auth import login_required
from server.services.session_runtime import current_user
from tools.data.account_manage import get_account, load_accounts

_SOURCE_CATALOG = FactorSourceCatalog()


@factor_library_internal_bp.route('/families', methods=['GET'])
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


@factor_library_internal_bp.route('/families/public/<factor_name>', methods=['GET'])
@login_required
def api_public_factor_detail(factor_name):
    detail = get_public_factor_detail(factor_name)
    if detail is None:
        return jsonify({'success': False, 'error': f'公共因子 "{factor_name}" 不存在'}), 404
    return jsonify({'success': True, 'factor': detail})


@factor_library_internal_bp.route('/family-sources/<source_kind>/<factor_id>/versions', methods=['GET'])
@login_required
def api_source_versions(source_kind, factor_id):
    username = cast(str, current_user())
    try:
        return jsonify(_SOURCE_CATALOG.versions(
            username, source_kind, factor_id,
            owner_username=str(request.args.get('owner_username') or ''),
            limit=request.args.get('limit', 100),
        ))
    except PermissionError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 403
    except (FileNotFoundError, ValueError) as exc:
        return jsonify({'success': False, 'error': str(exc)}), 404


@factor_library_internal_bp.route(
    '/family-sources/<source_kind>/<factor_id>/versions/<fingerprint>',
    methods=['GET'],
)
@login_required
def api_source_version(source_kind, factor_id, fingerprint):
    username = cast(str, current_user())
    try:
        return jsonify(_SOURCE_CATALOG.version(
            username, source_kind, factor_id, fingerprint,
            owner_username=str(request.args.get('owner_username') or ''),
        ))
    except PermissionError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 403
    except (FileNotFoundError, ValueError) as exc:
        return jsonify({'success': False, 'error': str(exc)}), 404
