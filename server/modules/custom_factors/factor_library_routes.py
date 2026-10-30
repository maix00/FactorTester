"""Routes for factor-library parameter configurations."""
from __future__ import annotations

from flask import jsonify, request

from server.modules.custom_factors import factor_library_internal_bp
from server.modules.custom_factors.factor_library_service import (
    build_factor_library_overview,
    delete_factor_library_factor,
    list_factor_library_config_users,
    list_factor_library_product_groups,
    save_current_user_library_config,
    save_single_library_factor,
)
from server.modules.custom_factors.factor_library_store import (
    DEFAULT_SCOPE_KEY,
    delete_factor_param_config,
    delete_scope,
    ensure_scope_exists,
    load_factor_param_config,
    list_factor_param_config_refs,
    normalize_product_group,
    rename_scope,
)
from server.services.api_response import api_ok, route_guard
from server.services.factor_registry import get_factor_family_instance
from server.services.http_auth import login_required
from server.services.session_runtime import current_user, user_file_lock_budget, get_user_file_lock
from server.identity.keycloak_authorization import (
    AuthorizationUnavailable,
    ensure_keycloak_resource,
    keycloak_authorized_objects,
    keycloak_request_credentials,
    keycloak_resource_permission,
)


def _username() -> str | None:
    u = current_user()
    if u is None:
        return None
    return u


def _factor_library_resource_ref(owner_username: str) -> str:
    return f"custom:{str(owner_username or '').strip()}"


def _ensure_own_factor_library_resource(owner_username: str) -> tuple[str, str, str] | None:
    from flask import g, has_request_context

    credentials = keycloak_request_credentials()
    if credentials is None or credentials[2] != str(owner_username):
        return None
    resource_ref = _factor_library_resource_ref(owner_username)
    registered = getattr(g, "_tr_factor_libraries_registered", None) if has_request_context() else None
    if isinstance(registered, set) and resource_ref in registered:
        return credentials
    ensure_keycloak_resource(
        resource_type="factor_library",
        resource_ref=resource_ref,
        owner_subject=credentials[1],
    )
    if has_request_context():
        if not isinstance(registered, set):
            registered = set()
            g._tr_factor_libraries_registered = registered
        registered.add(resource_ref)
    return credentials


def _authorize_factor_library(owner_username: str, scope: str):
    credentials = keycloak_request_credentials()
    if credentials is None:
        return jsonify({'success': False, 'error': '需要有效的 Keycloak 会话'}), 401
    if credentials[2] == str(owner_username):
        try:
            credentials = _ensure_own_factor_library_resource(owner_username)
        except Exception as exc:
            return jsonify({
                'success': False, 'code': 'authorization_unavailable',
                'error': str(exc),
            }), 503
        if credentials is None:
            return jsonify({'success': False, 'error': 'Keycloak 身份不匹配'}), 403
    try:
        allowed = keycloak_resource_permission(
            credentials[0], resource_type="factor_library",
            resource_ref=_factor_library_resource_ref(owner_username), scope=scope,
        )
    except Exception as exc:
        return jsonify({
            'success': False, 'code': 'authorization_unavailable',
            'error': str(exc),
        }), 503
    if not allowed:
        return jsonify({'success': False, 'error': 'Keycloak 未授予此因子库操作'}), 403
    return None


def _authorized_library_owners(username: str, *, include_shared: bool,
                                refs: list[tuple[str, str, str]]) -> tuple[set[str], object | None]:
    credentials = keycloak_request_credentials()
    if credentials is None:
        return set(), (jsonify({'success': False, 'error': '需要有效的 Keycloak 会话'}), 401)
    if credentials[2] != str(username):
        return set(), (jsonify({'success': False, 'error': 'Keycloak 身份不匹配'}), 403)
    owners = {str(owner) for owner, _family, _scope in refs if owner}
    owners.add(str(username))
    if not include_shared:
        owners = {str(username)}
    try:
        _ensure_own_factor_library_resource(username)
        allowed = keycloak_authorized_objects(
            credentials[0],
            resource_type="factor_library",
            refs=[(_factor_library_resource_ref(owner), owner) for owner in sorted(owners)],
            scope="read",
        )
    except Exception as exc:
        return set(), (jsonify({
            'success': False, 'code': 'authorization_unavailable',
            'error': str(exc),
        }), 503)
    return {str(owner) for owner in allowed}, None


def _can_filter_organization() -> bool:
    credentials = keycloak_request_credentials()
    if credentials is None:
        return False
    from flask import g

    identity = getattr(g, "keycloak_user_session", None)
    roles = identity.get("keycloak_roles", ()) if isinstance(identity, dict) else ()
    return "admin_console:manage" in roles


@factor_library_internal_bp.route('/overview', methods=['GET'])
@login_required
def api_factor_library_overview():
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    include_subordinates = request.args.get('include_subordinates') == '1'
    product_group = request.args.get('product_group') or request.args.get('scope_key') or None
    factor_family_alias = request.args.get('factor_family_alias') or None
    refs = list_factor_param_config_refs(scope_key=product_group)
    owners, failure = _authorized_library_owners(
        username, include_shared=include_subordinates, refs=refs,
    )
    if failure:
        return failure
    payload = build_factor_library_overview(
        username, include_subordinates, product_group=product_group,
        factor_family_alias=factor_family_alias, authorized_owners=owners,
        can_filter_organization=_can_filter_organization(),
    )
    return jsonify({'success': True, **payload})


@factor_library_internal_bp.route('/configurations/<ff_alias>', methods=['GET'])
@login_required
def api_factor_library_configs(ff_alias):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    product_group = request.args.get('product_group') or request.args.get('scope_key') or DEFAULT_SCOPE_KEY
    refs = list_factor_param_config_refs(ff_alias=ff_alias, scope_key=product_group)
    owners, failure = _authorized_library_owners(
        username, include_shared=True, refs=refs,
    )
    if failure:
        return failure
    payload = list_factor_library_config_users(
        username, ff_alias, product_group=product_group,
        authorized_owners=owners,
        can_filter_organization=_can_filter_organization(),
    )
    return jsonify({'success': True, **payload})


@factor_library_internal_bp.route('/configurations/<ff_alias>/<owner_username>', methods=['GET'])
@login_required
def api_get_factor_library_config(ff_alias, owner_username):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    product_group = request.args.get('product_group') or request.args.get('scope_key') or DEFAULT_SCOPE_KEY
    failure = _authorize_factor_library(owner_username, "read")
    if failure:
        return failure
    config = load_factor_param_config(owner_username, ff_alias, scope_key=product_group)
    if not config:
        return jsonify({'success': False, 'error': '该用户尚未保存因子库参数配置'}), 404
    config = dict(config)
    config['owner_username'] = owner_username
    manage_failure = _authorize_factor_library(owner_username, "manage")
    config['editable'] = manage_failure is None
    return jsonify({'success': True, 'config': config})


@factor_library_internal_bp.route('/configurations/<ff_alias>', methods=['PUT'])
@login_required
@route_guard
def api_save_factor_library_config(ff_alias):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    data = request.get_json() or {}
    params_list = data.get('params_list', [])
    product_group = data.get('product_group') or data.get('scope_key') or DEFAULT_SCOPE_KEY
    metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}
    for key in ('note', 'research_report', 'product_group_paths'):
        if key in data and key not in metadata:
            metadata[key] = data.get(key)
    if not isinstance(params_list, list):
        return jsonify({'success': False, 'error': '参数列表格式无效'})
    failure = _authorize_factor_library(username, "write")
    if failure:
        return failure
    with user_file_lock_budget(username):
        config, factors = save_current_user_library_config(
            username,
            ff_alias,
            params_list,
            product_group=product_group,
            metadata=metadata,
        )
    return api_ok({'config': config, 'factors': factors})


@factor_library_internal_bp.route('/configurations/<ff_alias>', methods=['DELETE'])
@login_required
def api_delete_factor_library_config(ff_alias):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    scope_key = request.args.get('product_group') or request.args.get('scope_key') or DEFAULT_SCOPE_KEY
    factor_alias = str(request.args.get('factor_alias') or '').strip()
    failure = _authorize_factor_library(username, "delete")
    if failure:
        return failure
    with user_file_lock_budget(username):
        deleted = (
            delete_factor_library_factor(
                username, ff_alias, factor_alias, product_group=scope_key,
            )
            if factor_alias else delete_factor_param_config(
                username, ff_alias, scope_key=scope_key,
            )
        )
    if not deleted:
        return jsonify({'success': False, 'error': '因子或配置不存在'}), 404
    return jsonify({'success': True})


@factor_library_internal_bp.route('/configurations/<ff_alias>/factors', methods=['POST'])
@login_required
def api_add_factor_to_library_config(ff_alias):
    """从当前会话参数中，将一个因子追加到用户因子库配置中。"""
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    data = request.get_json() or {}
    if 'params' in data:
        if not isinstance(data['params'], dict):
            return jsonify({'success': False, 'error': '因子参数格式无效'}), 400
        if data.get('mode') == 'edit' and not str(data.get('replace_factor_ref') or '').strip():
            return jsonify({'success': False, 'error': '编辑目标缺少冻结引用，请刷新后重试'}), 409
        failure = _authorize_factor_library(username, "write")
        if failure:
            return failure
        try:
            with user_file_lock_budget(username):
                config, factor = save_single_library_factor(
                    username, ff_alias, data['params'],
                    product_group=data.get('product_group') or data.get('scope_key') or DEFAULT_SCOPE_KEY,
                    metadata=data.get('metadata') if isinstance(data.get('metadata'), dict) else {},
                    replace_factor_ref=str(data.get('replace_factor_ref') or ''),
                )
        except ValueError as exc:
            from server.manager.storage.account_domain.payloads import PayloadTooLarge

            if isinstance(exc, PayloadTooLarge):
                return jsonify({
                    'success': False, 'error': str(exc),
                    'payload_bytes': exc.byte_length,
                    'field_sizes': exc.field_sizes,
                }), 409
            return jsonify({'success': False, 'error': str(exc)}), 409
        except ImportError as exc:
            # A registration can outlive the family source it was frozen from
            # (deleted or never uploaded).  That is a client-visible conflict,
            # not a server fault, so answer 404 instead of an HTML 500.
            return jsonify({'success': False, 'error': str(exc)}), 404
        return api_ok({'config': config, 'factor': factor, 'factors': [factor]})
    factor_alias = (data.get('factor_alias') or '').strip()
    product_group = data.get('product_group') or data.get('scope_key') or DEFAULT_SCOPE_KEY
    scope_key = normalize_product_group(product_group)
    if not factor_alias:
        return jsonify({'success': False, 'error': '缺少 factor_alias'}), 400
    failure = _authorize_factor_library(username, "write")
    if failure:
        return failure

    # 从 page_factors 查找因子（因子是唯一数据源），提取其参数行。
    page_uuid = str(data.get('page_uuid') or '')
    try:
        factor_family = get_factor_family_instance(ff_alias, username=username)
    except ImportError:
        return jsonify({'success': False, 'error': f'因子族 {ff_alias} 不存在'}), 404

    matched_param = None
    if page_uuid:
        from server.services.factor_registry import page_factors
        factor = page_factors.get(page_uuid, {}).get(factor_alias)
        if factor is not None:
            matched_param = {
                p.alias: getattr(factor, p.alias, p.default_value)
                for p in factor_family.params
            }

    if matched_param is None:
        return jsonify({'success': False, 'error': f'未找到因子 {factor_alias} 对应的参数'}), 404

    # 读取当前 scope 下的已有配置，追加新参数行（去重）
    with user_file_lock_budget(username):
        existing_config = load_factor_param_config(username, ff_alias, scope_key=scope_key)
        existing_params = existing_config.get('params_list', []) if existing_config else []

        # 去重：检查是否已存在相同因子 alias 的参数行
        existing_aliases = set()
        for row in existing_params:
            row_alias = factor_family.get_alias(**row)
            if row_alias:
                existing_aliases.add(row_alias)

        if factor_alias in existing_aliases:
            return jsonify({'success': True, 'message': f'因子 {factor_alias} 已存在，无需重复添加', 'skipped': True})

        existing_params.append(matched_param)
        config, factors = save_current_user_library_config(username, ff_alias, existing_params, product_group=scope_key)

    return api_ok({'config': config, 'factors': factors})


# ── Scope management ──

@factor_library_internal_bp.route('/configuration-scopes', methods=['GET'])
@login_required
def api_list_scopes():
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    failure = _authorize_factor_library(username, "read")
    if failure:
        return failure
    product_groups = list_factor_library_product_groups(username)
    return jsonify({'success': True, 'scopes': product_groups, 'product_groups': product_groups})


@factor_library_internal_bp.route('/configuration-scopes/<scope_key>', methods=['PUT'])
@login_required
def api_ensure_scope(scope_key):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    failure = _authorize_factor_library(username, "manage")
    if failure:
        return failure
    with user_file_lock_budget(username):
        actual = ensure_scope_exists(username, scope_key)
    return jsonify({'success': True, 'scope_key': actual, 'product_group': actual})


@factor_library_internal_bp.route('/configuration-scopes/<scope_key>', methods=['PATCH'])
@login_required
def api_rename_scope(scope_key):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    failure = _authorize_factor_library(username, "manage")
    if failure:
        return failure
    data = request.get_json() or {}
    new_key = (data.get('new_product_group') or data.get('new_scope_key') or '').strip()
    if not new_key:
        return jsonify({'success': False, 'error': '新 scope key 不能为空'})
    if new_key == scope_key:
        return jsonify({'success': True, 'scope_key': scope_key, 'product_group': scope_key})
    with user_file_lock_budget(username):
        ok = rename_scope(username, scope_key, new_key)
    if not ok:
        return jsonify({'success': False, 'error': '重命名失败，源 scope 不存在或目标已存在'}), 400
    return jsonify({'success': True, 'scope_key': new_key, 'product_group': new_key})


@factor_library_internal_bp.route('/configuration-scopes/<scope_key>', methods=['DELETE'])
@login_required
def api_delete_scope(scope_key):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    failure = _authorize_factor_library(username, "delete")
    if failure:
        return failure
    with user_file_lock_budget(username):
        ok = delete_scope(username, scope_key)
    if not ok:
        return jsonify({'success': False, 'error': '无法删除默认或不存在'}), 400
    return jsonify({'success': True})
