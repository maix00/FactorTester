"""Routes for factor-library parameter configurations."""
from __future__ import annotations
from hashlib import sha256
import json

from flask import jsonify, request

from server.modules.custom_factors import cf_bp
from server.services.api_response import api_ok, route_guard
from server.modules.custom_factors.factor_library_service import (
    build_factor_library_overview,
    delete_factor_library_factor,
    list_factor_library_product_groups,
    list_factor_library_config_users,
    save_current_user_library_config,
)
from server.modules.custom_factors.client_library import (
    build_client_library_projection,
)
from server.modules.custom_factors.factor_library_store import (
    DEFAULT_SCOPE_KEY,
    delete_factor_param_config,
    delete_scope,
    ensure_scope_exists,
    load_factor_param_config,
    normalize_product_group,
    rename_scope,
)
from tools.data.account_manage import (
    can_view_user_scope,
    delete_factor_research_run,
    list_factor_research_runs,
    save_factor_research_run,
    visible_usernames_for,
)
from tools.data.factor_research_registry import (
    RESEARCH_METRIC_REGISTRY,
    metric_float,
    parse_metric_thresholds,
    research_stability_rows,
    resolve_research_rank_preset,
)
from server.services.factor_registry import get_factor_family_instance
from server.modules.custom_factors.factor_set_registry import (
    author_factor_set,
    factor_set_catalog,
    factor_set_detail,
    register_factor_set,
    unregister_factor_set,
)
from server.services.http_auth import login_required
from server.services.session_runtime import current_user, get_user_file_lock


def _username() -> str | None:
    u = current_user()
    if u is None:
        return None
    return u


@cf_bp.route('/api/factor-library-overview', methods=['GET'])
@login_required
def api_factor_library_overview():
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    include_subordinates = request.args.get('include_subordinates') == '1'
    product_group = request.args.get('product_group') or request.args.get('scope_key') or None
    factor_family_alias = request.args.get('factor_family_alias') or None
    payload = build_factor_library_overview(username, include_subordinates, product_group=product_group, factor_family_alias=factor_family_alias)
    return jsonify({'success': True, **payload})


@cf_bp.route('/api/client/factor-library', methods=['GET'])
@login_required
def api_client_factor_library():
    """Return only registered, source-free metadata for embedded clients."""
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    include_subordinates = (
        request.args.get('include_subordinates') == '1'
    )
    payload = build_factor_library_overview(
        username,
        include_subordinates,
        product_group=(
            request.args.get('product_group')
            or request.args.get('scope_key')
            or None
        ),
        factor_family_alias=(
            request.args.get('factor_family_alias') or None
        ),
    )
    return jsonify({
        'success': True,
        **build_client_library_projection(
            payload,
            principal=username,
        ),
    })


@cf_bp.route('/api/client/factor-sets', methods=['GET', 'POST', 'DELETE'])
@login_required
def api_client_factor_sets():
    """Read or explicitly synchronize user-owned immutable factor sets."""
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    if request.method == 'GET':
        items = factor_set_catalog(username, request.args.get('query') or '')
        return jsonify({'success': True, 'count': len(items), 'items': items})
    if request.method == 'DELETE':
        target_ref = str(request.args.get('target_ref') or '')
        if not target_ref:
            return jsonify({'success': False, 'error': 'target_ref 不能为空'}), 400
        return jsonify({
            'success': unregister_factor_set(username, target_ref),
        })
    data = request.get_json(silent=True) or {}
    definition = data.get('definition')
    if isinstance(definition, dict):
        try:
            value = author_factor_set(
                username,
                definition,
                persist=data.get('persist') is not False,
                replace_target_ref=str(data.get('replace_target_ref') or ''),
            )
        except ValueError as exc:
            return jsonify({'success': False, 'error': str(exc)}), 400
        return jsonify({'success': True, 'factor_set': value})
    descriptor = data.get('descriptor')
    if not isinstance(descriptor, dict):
        return jsonify({'success': False, 'error': 'descriptor 必须是对象'}), 400
    try:
        value = register_factor_set(username, descriptor)
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    return jsonify({'success': True, 'factor_set': value})


@cf_bp.route('/api/client/factor-sets/detail', methods=['GET'])
@login_required
def api_client_factor_set_detail():
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    target_ref = str(request.args.get('target_ref') or '')
    try:
        offset = max(0, int(request.args.get('offset') or 0))
        limit = min(100, max(1, int(request.args.get('limit') or 100)))
    except ValueError:
        return jsonify({'success': False, 'error': '分页参数无效'}), 400
    value = factor_set_detail(
        username, target_ref, offset=offset, limit=limit,
    )
    if value is None:
        return jsonify({'success': False, 'error': 'Factor Set 不存在'}), 404
    return jsonify({'success': True, 'factor_set': value})


@cf_bp.route(
    '/api/client/factor-library-sources/<owner_username>/projection',
    methods=['GET'],
)
@login_required
def api_client_factor_library_projection(owner_username):
    """Return a bounded, source-free initialization projection."""
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    if not can_view_user_scope(username, owner_username):
        return jsonify({'success': False, 'error': '无权查看该用户因子库'}), 403
    payload = build_factor_library_overview(
        username,
        True,
        product_group=request.args.get('product_group') or None,
    )
    allowed = {
        'factor_alias', 'factor_family_alias', 'factor_family_name',
        'category', 'params', 'owner_username', 'owner_alias',
        'scope_key', 'product_group', 'updated_at',
    }
    factors = [
        {key: item.get(key) for key in sorted(allowed) if key in item}
        for item in payload.get('factors', [])
        if item.get('owner_username') == owner_username
    ]
    projection = {
        'schema_version': 1,
        'principal': username,
        'owner_ref': owner_username,
        'factors': factors,
    }
    encoded = json.dumps(
        projection, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'),
    ).encode()
    return jsonify({
        'success': True,
        'projection': projection,
        'projection_hash': sha256(encoded).hexdigest(),
    })


@cf_bp.route('/api/client/factor-library-sources', methods=['GET'])
@login_required
def api_client_factor_library_sources():
    """List server-authorized source owners without returning source code."""
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    payload = build_factor_library_overview(username, True)
    counts: dict[str, int] = {}
    aliases: dict[str, str] = {}
    for factor in payload.get('factors', []):
        owner = str(factor.get('owner_username') or '').strip()
        if not owner or not can_view_user_scope(username, owner):
            continue
        counts[owner] = counts.get(owner, 0) + 1
        aliases[owner] = str(factor.get('owner_alias') or owner)
    return jsonify({
        'success': True,
        'principal': username,
        'sources': [
            {
                'owner_ref': owner,
                'owner_alias': aliases[owner],
                'factor_count': counts[owner],
            }
            for owner in sorted(counts)
        ],
    })


@cf_bp.route('/api/factor-library-configs/<ff_alias>', methods=['GET'])
@login_required
def api_factor_library_configs(ff_alias):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    product_group = request.args.get('product_group') or request.args.get('scope_key') or DEFAULT_SCOPE_KEY
    payload = list_factor_library_config_users(username, ff_alias, product_group=product_group)
    return jsonify({'success': True, **payload})


@cf_bp.route('/api/factor-library-configs/<ff_alias>/<owner_username>', methods=['GET'])
@login_required
def api_get_factor_library_config(ff_alias, owner_username):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    if not can_view_user_scope(username, owner_username):
        return jsonify({'success': False, 'error': '无权查看该用户配置'}), 403
    product_group = request.args.get('product_group') or request.args.get('scope_key') or DEFAULT_SCOPE_KEY
    config = load_factor_param_config(owner_username, ff_alias, scope_key=product_group)
    if not config:
        return jsonify({'success': False, 'error': '该用户尚未保存因子库参数配置'}), 404
    config = dict(config)
    config['owner_username'] = owner_username
    config['editable'] = owner_username == username
    return jsonify({'success': True, 'config': config})


@cf_bp.route('/api/factor-library-configs/<ff_alias>', methods=['PUT'])
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
    with get_user_file_lock(username):
        config, factors = save_current_user_library_config(
            username,
            ff_alias,
            params_list,
            product_group=product_group,
            metadata=metadata,
        )
    return api_ok({'config': config, 'factors': factors})


@cf_bp.route('/api/factor-library-configs/<ff_alias>', methods=['DELETE'])
@login_required
def api_delete_factor_library_config(ff_alias):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    scope_key = request.args.get('product_group') or request.args.get('scope_key') or DEFAULT_SCOPE_KEY
    factor_alias = str(request.args.get('factor_alias') or '').strip()
    with get_user_file_lock(username):
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


@cf_bp.route('/api/factor-library-configs/<ff_alias>/add-factor', methods=['POST'])
@login_required
def api_add_factor_to_library_config(ff_alias):
    """从当前会话参数中，将一个因子追加到用户因子库配置中。"""
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    data = request.get_json() or {}
    factor_alias = (data.get('factor_alias') or '').strip()
    product_group = data.get('product_group') or data.get('scope_key') or DEFAULT_SCOPE_KEY
    scope_key = normalize_product_group(product_group)
    if not factor_alias:
        return jsonify({'success': False, 'error': '缺少 factor_alias'}), 400

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
    with get_user_file_lock(username):
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

@cf_bp.route('/api/factor-library-scopes', methods=['GET'])
@login_required
def api_list_scopes():
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    product_groups = list_factor_library_product_groups(username)
    return jsonify({'success': True, 'scopes': product_groups, 'product_groups': product_groups})


@cf_bp.route('/api/factor-library-scopes/<scope_key>', methods=['PUT'])
@login_required
def api_ensure_scope(scope_key):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    with get_user_file_lock(username):
        actual = ensure_scope_exists(username, scope_key)
    return jsonify({'success': True, 'scope_key': actual, 'product_group': actual})


@cf_bp.route('/api/factor-library-scopes/<scope_key>', methods=['PATCH'])
@login_required
def api_rename_scope(scope_key):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    data = request.get_json() or {}
    new_key = (data.get('new_product_group') or data.get('new_scope_key') or '').strip()
    if not new_key:
        return jsonify({'success': False, 'error': '新 scope key 不能为空'})
    if new_key == scope_key:
        return jsonify({'success': True, 'scope_key': scope_key, 'product_group': scope_key})
    with get_user_file_lock(username):
        ok = rename_scope(username, scope_key, new_key)
    if not ok:
        return jsonify({'success': False, 'error': '重命名失败，源 scope 不存在或目标已存在'}), 400
    return jsonify({'success': True, 'scope_key': new_key, 'product_group': new_key})


@cf_bp.route('/api/factor-library-scopes/<scope_key>', methods=['DELETE'])
@login_required
def api_delete_scope(scope_key):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    with get_user_file_lock(username):
        ok = delete_scope(username, scope_key)
    if not ok:
        return jsonify({'success': False, 'error': '无法删除默认或不存在'}), 400
    return jsonify({'success': True})


def _metric_thresholds(prefix: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for raw in request.args.getlist(prefix):
        if ':' in raw:
            key, value = raw.split(':', 1)
        elif '=' in raw:
            key, value = raw.split('=', 1)
        else:
            continue
        key = key.strip()
        if not key:
            continue
        try:
            result[key] = float(value)
        except ValueError:
            continue
    return result


def _research_query_limit() -> int | None:
    limit_arg = request.args.get('limit')
    try:
        return int(limit_arg) if limit_arg not in (None, '') else None
    except ValueError:
        return None


def _list_visible_research_runs(
    username: str,
    *,
    limit: int | None = None,
    resolved_test_type: str | None = None,
    apply_metric_filters: bool = True,
) -> list[dict]:
    include_subordinates = request.args.get('include_subordinates') == '1'
    usernames = visible_usernames_for(username) if include_subordinates else [username]
    runs: list[dict] = []
    for visible_username in usernames:
        runs.extend(
            list_factor_research_runs(
                visible_username,
                ff_alias=request.args.get('factor_family') or request.args.get('ff_alias') or None,
                factor_alias=request.args.get('factor_alias') or None,
                product_group=request.args.get('product_group') or None,
                test_type=resolved_test_type if resolved_test_type is not None else (request.args.get('test_type') or None),
                sample_role=request.args.get('sample_role') or None,
                regime_label=request.args.get('regime_label') or None,
                slice_name=request.args.get('slice_name') or None,
                start_date=request.args.get('start_date') or None,
                end_date=request.args.get('end_date') or None,
                overlap=request.args.get('overlap', '1') != '0',
                min_metrics=(_metric_thresholds('min_metric') or None) if apply_metric_filters else None,
                max_metrics=(_metric_thresholds('max_metric') or None) if apply_metric_filters else None,
                order_by_metric=None,
                descending=True,
                limit=None,
            )
        )
    order_by_metric = request.args.get('order_by_metric') or request.args.get('metric') or None
    descending = request.args.get('ascending') != '1'
    if order_by_metric:
        missing_rank = float('-inf') if descending else float('inf')
        runs.sort(
            key=lambda run: metric_float((run.get('metrics') or {}).get(order_by_metric)) if metric_float((run.get('metrics') or {}).get(order_by_metric)) is not None else missing_rank,
            reverse=descending,
        )
    else:
        runs.sort(key=lambda run: float(run.get('updated_at') or 0), reverse=True)
    if limit is not None and limit >= 0:
        runs = runs[:limit]
    return runs


@cf_bp.route('/api/factor-library-research-runs', methods=['GET'])
@login_required
def api_list_factor_research_runs():
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    runs = _list_visible_research_runs(username, limit=_research_query_limit())
    return jsonify({'success': True, 'runs': runs})


@cf_bp.route('/api/factor-library-research-runs', methods=['POST'])
@login_required
@route_guard
def api_save_factor_research_run():
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    data = request.get_json() or {}
    metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else {}
    try:
        run = save_factor_research_run(
            username,
            ff_alias=str(data.get('ff_alias') or data.get('factor_family') or ''),
            factor_alias=str(data.get('factor_alias') or ''),
            factor_source=str(data.get('factor_source') or ''),
            product_group=str(data.get('product_group') or ''),
            start_date=str(data.get('start_date') or ''),
            end_date=str(data.get('end_date') or ''),
            test_type=str(data.get('test_type') or ''),
            config=data.get('config') if isinstance(data.get('config'), dict) else {},
            config_hash_value=str(data.get('config_hash') or ''),
            metrics=metrics,
            report_path=str(data.get('report_path') or ''),
            artifact_path=str(data.get('artifact_path') or ''),
            note=str(data.get('note') or ''),
            sample_role=str(data.get('sample_role') or ''),
            regime_label=str(data.get('regime_label') or ''),
            slice_name=str(data.get('slice_name') or ''),
            run_id=str(data.get('run_id') or '') or None,
        )
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    return jsonify({'success': True, 'run': run})


@cf_bp.route('/api/factor-library-research-metrics', methods=['GET'])
@login_required
def api_factor_research_metrics():
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    test_type = request.args.get('test_type') or ''
    metrics = {
        key: value
        for key, value in RESEARCH_METRIC_REGISTRY.items()
        if not test_type or value.get('default_test_type') == test_type
    }
    return jsonify({'success': True, 'metrics': metrics})


@cf_bp.route('/api/factor-library-research-stability', methods=['GET'])
@login_required
def api_factor_research_stability():
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    resolved = resolve_research_rank_preset(
        preset=request.args.get('preset') or '',
        test_type=request.args.get('test_type') or '',
        metric=request.args.get('metric') or '',
        min_metrics=request.args.getlist('min_metric'),
        max_metrics=request.args.getlist('max_metric'),
    )
    try:
        min_metrics = parse_metric_thresholds(resolved['min_metrics'])
        max_metrics = parse_metric_thresholds(resolved['max_metrics'])
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    runs = _list_visible_research_runs(
        username,
        limit=_research_query_limit(),
        resolved_test_type=resolved['test_type'] or None,
        apply_metric_filters=False,
    )
    rows = research_stability_rows(
        runs,
        metric=resolved['metric'],
        min_metrics=min_metrics,
        max_metrics=max_metrics,
        bucket=request.args.get('by') or request.args.get('bucket') or 'quarter',
    )
    return jsonify({'success': True, 'rows': rows, 'preset': resolved})


@cf_bp.route('/api/factor-library-research-runs/<run_id>', methods=['DELETE'])
@login_required
def api_delete_factor_research_run(run_id):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    deleted = delete_factor_research_run(username, run_id)
    if not deleted:
        return jsonify({'success': False, 'error': '研究结果不存在'}), 404
    return jsonify({'success': True})
