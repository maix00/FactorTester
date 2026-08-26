"""Routes supporting custom-factor source validation and visual editor metadata."""

import hashlib
import json
import os

from flask import jsonify, request

from server.modules.custom_factors import cf_bp
from server.modules.custom_factors.expression_inspection import fixed_column_refs
from server.modules.custom_factors.visual_graph import factor_expr_to_visual_graph
from server.modules.shared.factor_param_utils import (
    factor_param_value_display,
    normalize_factor_param_row,
)
from server.modules.shared.param_meta import serialize_param_meta
from server.services.factor_registry import (
    get_factor_family_instance,
    invalidate_factor_family_cache,
)
from server.services.factor_workspace import (
    build_factor_workspace,
    get_factor_workspace_git_state,
    push_factor_workspace,
    run_factor_workspace_git_action,
    sync_factor_workspace,
)
from server.services.http_auth import login_required
from server.services.run_input_inspection import instantiate_factor_metadata
from server.services.session_runtime import current_user
from tools.data.account_manage import (
    can_view_user_scope,
    get_account,
    is_super_admin_account,
)
from tools.data.factor_workspace.storage import (
    assert_canonical_factor_workspace_root,
    factor_source_root,
    load_factor_source,
    load_public_factor_source,
)
from tools.data.sqlite.factor_source_store import list_factor_sources
from tools.factors.formula_identity import freeze_factor_identity


def _freeze_validated_factor(factor_family, params, owner_ref):
    """Return the canonical Factor v2 record without persisting it."""
    normalized = normalize_factor_param_row(factor_family, params)
    factor = factor_family.get_factor(**normalized)
    expression = getattr(factor, '_source_expr', None) or factor.expr
    display_params = {
        parameter.alias: factor_param_value_display(
            parameter, normalized.get(parameter.alias),
        )
        for parameter in factor_family.params
    }
    return freeze_factor_identity(
        owner_ref=str(owner_ref or '').strip(),
        family_alias=str(getattr(factor_family, 'alias', '') or '').strip(),
        factor_alias=str(factor.alias),
        family_formula_fingerprint=factor_family.expr.semantic_fingerprint(),
        self_formula_fingerprint=expression.semantic_fingerprint(),
        params=display_params,
    )


@cf_bp.route('/api/internal/public-source-applied', methods=['POST'])
@login_required
def api_public_source_applied():
    username = current_user()
    if not is_super_admin_account(get_account(username)):
        return jsonify({'success': False, 'error': '只有超级管理员可以同步公共因子家族'}), 403
    values = (request.get_json(silent=True) or {}).get('factors') or []
    if not isinstance(values, list) or len(values) > 256:
        return jsonify({'success': False, 'error': '公共因子同步清单无效'}), 400
    applied = []
    for value in values:
        if not isinstance(value, dict):
            return jsonify({'success': False, 'error': '公共因子同步项无效'}), 400
        factor_id = str(value.get('factor_id') or '').strip()
        source = load_public_factor_source(factor_id) or ''
        raw = source.encode('utf-8')
        if (
            not factor_id
            or len(raw) != int(value.get('source_bytes') or -1)
            or hashlib.sha256(raw).hexdigest()
            != str(value.get('source_sha256') or '').lower()
        ):
            return jsonify({
                'success': False,
                'error': f'公共因子源码校验失败: {factor_id}',
            }), 409
        invalidate_factor_family_cache(factor_id)
        applied.append(factor_id)
    return jsonify({'success': True, 'applied': applied})


@cf_bp.route('/api/validate', methods=['POST'])
@login_required
def api_validate_expr():
    data = request.get_json(silent=True) or {}
    username = current_user()

    if data.get('resolve_factor') and data.get('factor_family_alias'):
        family_alias = str(data.get('factor_family_alias') or '').strip()
        owner_username = str(
            data.get('owner_username') or username or ''
        ).strip()
        is_public = bool(data.get('is_public')) or owner_username in {
            'public', '__public_jobs__',
        }
        family_ref = (
            f'public:{family_alias}' if is_public
            else f'{owner_username}:{family_alias}'
        )
        try:
            factor_family = get_factor_family_instance(
                family_ref, username=username,
            )
            instance = instantiate_factor_metadata(
                factor_family, data.get('params'),
            )
            owner_ref = 'public' if is_public else owner_username
            return jsonify({
                'success': True,
                'valid': True,
                'error': None,
                'factor_name': factor_family.__class__.__name__,
                'params': [
                    serialize_param_meta(param)
                    for param in factor_family.params
                ],
                'desc': getattr(factor_family, 'desc', '') or '',
                'description': getattr(factor_family, 'description', '') or '',
                'factor': _freeze_validated_factor(
                    factor_family, data.get('params'), owner_ref,
                ),
                **instance,
            })
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            return jsonify({
                'success': True,
                'valid': False,
                'error': f'因子解析失败: {exc!s}',
            })

    if data.get('is_public') and data.get('factor_name'):
        factor_name = data['factor_name']
        try:
            factor_family = get_factor_family_instance(factor_name)
            tree_repr = ''
            visual_graph = None
            if factor_family.expr is not None:
                tree_repr = factor_family.expr.tree_repr()
                visual_graph = factor_expr_to_visual_graph(factor_family.expr)
            instance = instantiate_factor_metadata(
                factor_family, data.get('params')
            )
            return jsonify({
                'success': True,
                'valid': True,
                'error': None,
                'tree_repr': tree_repr,
                'visual_graph': visual_graph,
                'column_refs': fixed_column_refs(factor_family.expr),
                'factor_name': factor_family.__class__.__name__,
                'params': [serialize_param_meta(param) for param in factor_family.params],
                'desc': getattr(factor_family, 'desc', '') or '',
                'description': getattr(factor_family, 'description', '') or '',
                'factor': _freeze_validated_factor(
                    factor_family, data.get('params'), 'public',
                ),
                **instance,
            })
        except Exception as exc:
            return jsonify({
                'success': True,
                'valid': False,
                'error': f'因子加载失败: {exc!s}',
                'tree_repr': '',
            })

    source_code = (data.get('source_code') or '').strip()
    factor_id = (data.get('factor_id') or '').strip()
    owner_username = (data.get('owner_username') or username or '').strip()

    if not source_code and factor_id:
        if not can_view_user_scope(username, owner_username):
            return jsonify({'success': True, 'valid': False, 'error': '无权查看该用户因子'})
        loaded_source = load_factor_source(owner_username, factor_id) or ''
        source_code = loaded_source

    if not source_code:
        return jsonify({'success': True, 'valid': False, 'error': '源码不能为空'})

    try:
        import importlib.util
        import os as _os
        import re
        import tempfile

        class_match = re.search(r'^\s*class\s+(\w+)\s*\(', source_code, re.MULTILINE)
        class_name = class_match.group(1) if class_match else 'ValidateFactor'

        tmpdir = tempfile.mkdtemp(prefix='cf_validate_')
        tmpfile = _os.path.join(tmpdir, f'{class_name}.py')
        try:
            with open(tmpfile, 'w', encoding='utf-8') as file:
                file.write(source_code)

            spec = importlib.util.spec_from_file_location(class_name, tmpfile)
            if spec is None or spec.loader is None:
                return jsonify({'success': True, 'valid': False, 'error': '无法加载源码模块'})

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            from tools.factors import FactorFamily
            factor_cls = None
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if isinstance(obj, type) and issubclass(obj, FactorFamily) and obj is not FactorFamily:
                    factor_cls = obj
                    break
            if factor_cls is None:
                return jsonify({'success': True, 'valid': False, 'error': '源码中未找到 FactorFamily 子类'})

            factor_family = factor_cls()
            tree_repr = ''
            visual_graph = None
            if factor_family.expr is not None:
                tree_repr = factor_family.expr.tree_repr()
                visual_graph = factor_expr_to_visual_graph(factor_family.expr)
            instance = instantiate_factor_metadata(
                factor_family, data.get('params')
            )
            owner_ref = str(
                data.get('owner_ref')
                or ('public' if data.get('is_public') else username)
                or ''
            ).strip()

            return jsonify({
                'success': True,
                'valid': True,
                'error': None,
                'tree_repr': tree_repr,
                'visual_graph': visual_graph,
                'column_refs': fixed_column_refs(factor_family.expr),
                'factor_name': factor_cls.__name__,
                'params': [serialize_param_meta(param) for param in factor_family.params],
                'desc': str(data.get('chinese_name') or ''),
                'description': str(data.get('description') or ''),
                'factor': _freeze_validated_factor(
                    factor_family, data.get('params'), owner_ref,
                ),
                **instance,
            })

        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    except SyntaxError as exc:
        return jsonify({'success': True, 'valid': False, 'error': f'语法错误: {exc.msg}'})
    except Exception as exc:
        import traceback
        return jsonify({
            'success': True,
            'valid': False,
            'error': f'{type(exc).__name__}: {exc!s}',
            'traceback': traceback.format_exc(),
        })


@cf_bp.route('/api/visual-operators')
@login_required
def api_visual_operators():
    from tools.factors.FactorExpr import get_visual_operator_groups
    return jsonify({
        'success': True,
        'groups': get_visual_operator_groups(),
    })


@cf_bp.route('/api/source-root', methods=['GET', 'POST'])
@login_required
def api_source_root():
    username = current_user()
    if request.method == 'GET':
        from tools.data.sqlite.factor_source_settings import load_factor_source_root
        configured_root = load_factor_source_root(username) or ''
        return jsonify({
            'success': True,
            'source_root': configured_root,
            'resolved_root': factor_source_root(username),
        })

    data = request.get_json(silent=True) or {}
    source_root = (data.get('source_root') or '').strip()
    if source_root:
        source_root = os.path.abspath(os.path.expanduser(source_root))
        try:
            source_root = assert_canonical_factor_workspace_root(source_root)
        except PermissionError as exc:
            return jsonify({'success': False, 'error': str(exc)}), 400

    from tools.data.sqlite.factor_source_settings import save_factor_source_root
    save_factor_source_root(username, source_root)
    return jsonify({
        'success': True,
        'source_root': source_root,
        'resolved_root': factor_source_root(username),
    })


@cf_bp.route('/api/workspace/build', methods=['POST'])
@login_required
def api_build_workspace():
    username = current_user()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    result = build_factor_workspace(username)
    return jsonify({'success': True, **result})


@cf_bp.route('/api/workspace/sync', methods=['POST'])
@login_required
def api_sync_workspace():
    username = current_user()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    branch_mode = (data.get('branch_mode') or 'force').strip()
    result = sync_factor_workspace(username, branch_mode=branch_mode)
    return jsonify({'success': True, **result})


@cf_bp.route('/api/workspace/push', methods=['POST'])
@login_required
def api_push_workspace():
    username = current_user()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    branch_mode = (data.get('branch_mode') or 'auto').strip()
    result = push_factor_workspace(
        username,
        allow_public_write=is_super_admin_account(get_account(username)),
        branch_mode=branch_mode,
    )
    return jsonify({'success': True, **result})


@cf_bp.route('/api/workspace/git-settings', methods=['GET', 'POST'])
@login_required
def api_workspace_git_settings():
    username = current_user()
    if request.method == 'GET':
        return jsonify({'success': True, **get_factor_workspace_git_state(username)})

    data = request.get_json(silent=True) or {}
    from tools.data.sqlite.factor_source_workspace_settings import (
        save_factor_source_workspace_settings,
    )
    git_enabled = bool(data.get('git_enabled'))
    git_repo_root = (data.get('git_repo_root') or '').strip()
    if git_repo_root:
        try:
            git_repo_root = assert_canonical_factor_workspace_root(git_repo_root)
        except PermissionError as exc:
            return jsonify({'success': False, 'error': str(exc)}), 400
    save_factor_source_workspace_settings(
        username,
        git_enabled=git_enabled,
        git_repo_root=git_repo_root,
    )
    return jsonify({'success': True, **get_factor_workspace_git_state(username)})


@cf_bp.route('/api/workspace/git', methods=['POST'])
@login_required
def api_workspace_git_action():
    username = current_user()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    try:
        result = run_factor_workspace_git_action(
            username,
            str(data.get('action') or ''),
            message=str(data.get('message') or ''),
            branch=str(data.get('branch') or ''),
            create=bool(data.get('create')),
            cached=bool(data.get('cached')),
            stat=bool(data.get('stat')),
        )
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    return jsonify({'success': True, **result})


def _canonical_workspace_snapshot(username: str) -> dict:
    files = []
    for row in list_factor_sources('custom'):
        if row.get('owner_username') != username:
            continue
        factor_id = str(row.get('factor_id') or '').strip()
        source_code = str(row.get('source_code') or '')
        if factor_id and source_code:
            files.append({
                'path': f'custom_factors/{factor_id}.py',
                'kind': 'custom',
                'source_sha256': hashlib.sha256(source_code.encode('utf-8')).hexdigest(),
                'source_bytes': len(source_code.encode('utf-8')),
            })
    for row in list_factor_sources('public'):
        factor_id = str(row.get('factor_id') or '').strip()
        source_code = str(row.get('source_code') or '')
        if factor_id and source_code:
            files.append({
                'path': f'public_factors/{factor_id}.py',
                'kind': 'public',
                'source_sha256': hashlib.sha256(source_code.encode('utf-8')).hexdigest(),
                'source_bytes': len(source_code.encode('utf-8')),
            })
    files.sort(key=lambda item: item['path'])
    digest_payload = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    git_state = get_factor_workspace_git_state(username)
    return {
        'schema_version': 1,
        'principal': username,
        'workspace_root': git_state.get('workspace_root', ''),
        'git_head': git_state.get('git_head', ''),
        'git_current_branch': git_state.get('git_current_branch', ''),
        'digest': hashlib.sha256(digest_payload).hexdigest(),
        'custom_factor_count': sum(item['kind'] == 'custom' for item in files),
        'public_factor_count': sum(item['kind'] == 'public' for item in files),
        'files': files,
    }


@cf_bp.route('/api/workspace/snapshot', methods=['GET', 'POST'])
@login_required
def api_workspace_snapshot():
    username = current_user()
    if not username:
        return jsonify({'success': False, 'error': '未登录'}), 401
    if request.method == 'GET':
        return jsonify({'success': True, 'snapshot': _canonical_workspace_snapshot(username)})

    return jsonify({
        'success': False,
        'error': (
            'workspace snapshot 只读；源码同步必须通过 upload/download 分支流程，'
            '禁止直接导入 snapshot'
        ),
        'code': 'workspace_snapshot_write_disabled',
        'next_commands': [
            'factortester custom_factors workspace push',
            'factortester custom_factors workspace sync',
        ],
    }), 410




@cf_bp.route('/api/params/preset', methods=['GET'])
@login_required
def api_params_preset():
    presets = [
        {'type': 'DataColumn', 'label': '数据列', 'desc': '选择价格列（如 CLOSE、OPEN 等）', 'example_alias': '$P', 'example_default': 'CA'},
        {'type': 'Timedelta', 'label': '时间窗口', 'desc': '时间长度（如 5d、30min）', 'example_alias': '$F', 'example_default': '5d'},
        {'type': 'int', 'label': '整数', 'desc': '整数参数（如回看周期数）', 'example_alias': '$N', 'example_default': 20},
        {'type': 'float', 'label': '浮点数', 'desc': '小数参数（如阈值）', 'example_alias': '$T', 'example_default': 0.5},
        {'type': 'bool', 'label': '布尔值', 'desc': '开关参数（True/False）', 'example_alias': '$B', 'example_default': False},
        {'type': 'str', 'label': '字符串', 'desc': '字符串参数', 'example_alias': '$S', 'example_default': 'default'},
    ]
    return jsonify({'success': True, 'presets': presets})
