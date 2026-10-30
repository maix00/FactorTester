"""Routes for custom-factor catalog pages and read-only factor metadata."""
from __future__ import annotations

from typing import cast

from flask import jsonify, request

from server.modules.custom_factors import factor_library_internal_bp
from server.modules.custom_factors.catalog import (
    get_public_factor_detail,
    list_custom_factors,
    list_public_factors,
)
from server.services.factor_source_catalog import FactorSourceCatalog
from server.services.http_auth import login_required
from server.services.session_runtime import current_user
from tools.data.sqlite.factor_metadata import list_factor_summaries

_SOURCE_CATALOG = FactorSourceCatalog()


def _keycloak_filter_factor_summaries(username: str, values: list[dict]) -> list[dict]:
    from server.identity.keycloak_authorization import (
        AuthorizationUnavailable,
        keycloak_authorized_factor_sources,
        keycloak_request_credentials,
    )

    credentials = keycloak_request_credentials()
    if credentials is None or credentials[2] != username:
        raise PermissionError("verified Keycloak session is required")
    allowed = keycloak_authorized_factor_sources(
        credentials[0], refs=[
            (
                str(item.get("owner_username") or username).strip(),
                str(item.get("id") or item.get("factor_id") or "").strip(),
            )
            for item in values
        ],
        scope="read",
    )
    return [
        item for item in values
        if (
            str(item.get("owner_username") or username).strip(),
            str(item.get("id") or item.get("factor_id") or "").strip(),
        ) in allowed
    ]


@factor_library_internal_bp.route('/families', methods=['GET'])
@login_required
def api_list_factors():
    username = cast(str, current_user())
    public = list_public_factors()
    include_subordinates = request.args.get('include_subordinates') == '1'
    if include_subordinates:
        # The local account tree is display/migration data, not an access
        # policy. Enumerate metadata only; Keycloak filters the candidates
        # before source bytes are loaded or family code is evaluated.
        custom = list_factor_summaries("custom", None)
        for factor in custom:
            owner = str(factor.get("owner_username") or "").strip()
            factor['owner_alias'] = owner or '未知用户'
            factor['can_edit'] = owner == username
    else:
        custom = list_custom_factors(username)
        for factor in custom:
            factor['owner_username'] = username
            factor['owner_alias'] = '我'
            factor['can_edit'] = True
    try:
        custom = _keycloak_filter_factor_summaries(username, custom)
    except PermissionError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 403
    except (FileNotFoundError, ValueError) as exc:
        return jsonify({'success': False, 'error': str(exc)}), 404
    except Exception as exc:
        from server.identity.keycloak_authorization import AuthorizationUnavailable
        if isinstance(exc, AuthorizationUnavailable):
            return jsonify({'success': False, 'error': str(exc),
                            'code': 'authorization_unavailable'}), 503
        raise

    from server.modules.custom_factors.crud_routes import _current_user_is_super_admin

    return jsonify({
        'success': True,
        'public_factors': public,
        'custom_factors': custom,
        'current_username': username,
        'is_admin': _current_user_is_super_admin(),
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
        if source_kind == "custom":
            from server.modules.custom_factors.crud_routes import _custom_factor_read_allowed

            owner = str(request.args.get('owner_username') or username).strip()
            if not _custom_factor_read_allowed(username, owner, factor_id):
                return jsonify({'success': False, 'error': '无权查看该用户因子'}), 403
        return jsonify(_SOURCE_CATALOG.versions(
            username, source_kind, factor_id,
            owner_username=str(request.args.get('owner_username') or ''),
            limit=request.args.get('limit', 100),
        ))
    except PermissionError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 403
    except Exception as exc:
        from server.identity.keycloak_authorization import AuthorizationUnavailable

        if isinstance(exc, AuthorizationUnavailable):
            return jsonify({'success': False, 'error': str(exc),
                            'code': 'authorization_unavailable'}), 503
        raise


@factor_library_internal_bp.route(
    '/family-sources/<source_kind>/<factor_id>/versions/<fingerprint>',
    methods=['GET'],
)
@login_required
def api_source_version(source_kind, factor_id, fingerprint):
    username = cast(str, current_user())
    try:
        if source_kind == "custom":
            from server.modules.custom_factors.crud_routes import _custom_factor_read_allowed

            owner = str(request.args.get('owner_username') or username).strip()
            if not _custom_factor_read_allowed(username, owner, factor_id):
                return jsonify({'success': False, 'error': '无权查看该用户因子'}), 403
        return jsonify(_SOURCE_CATALOG.version(
            username, source_kind, factor_id, fingerprint,
            owner_username=str(request.args.get('owner_username') or ''),
        ))
    except PermissionError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 403
    except (FileNotFoundError, ValueError) as exc:
        return jsonify({'success': False, 'error': str(exc)}), 404
    except Exception as exc:
        from server.identity.keycloak_authorization import AuthorizationUnavailable

        if isinstance(exc, AuthorizationUnavailable):
            return jsonify({'success': False, 'error': str(exc),
                            'code': 'authorization_unavailable'}), 503
        raise
