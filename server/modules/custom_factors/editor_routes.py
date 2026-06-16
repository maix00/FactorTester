"""Routes supporting custom-factor source validation and visual editor metadata."""

import os

from flask import jsonify, request

from server.modules.custom_factors import cf_bp
from server.modules.custom_factors.source_helpers import (
    assemble_factor_source,
    strip_factor_meta,
)
from server.modules.custom_factors.storage import load_factor_source
from server.modules.custom_factors.storage import factor_source_root
from server.modules.custom_factors.visual_graph import factor_expr_to_visual_graph
from server.modules.shared.param_meta import serialize_param_meta
from server.services.accounts import can_view_user_scope
from server.services.http_auth import login_required
from server.services.runtime_state import current_user
from server.services.accounts import get_account, is_super_admin_account
from server.services.factor_registry import get_factor_family_instance
from server.services.factor_workspace import build_factor_workspace, push_factor_workspace, sync_factor_workspace


@cf_bp.route('/api/validate', methods=['POST'])
@login_required
def api_validate_expr():
    data = request.get_json(silent=True) or {}
    username = current_user()

    if data.get('is_public') and data.get('factor_name'):
        factor_name = data['factor_name']
        try:
            factor_family = get_factor_family_instance(factor_name)
            tree_repr = ''
            visual_graph = None
            if factor_family.expr is not None:
                tree_repr = factor_family.expr.tree_repr()
                visual_graph = factor_expr_to_visual_graph(factor_family.expr)
            return jsonify({
                'success': True,
                'valid': True,
                'error': None,
                'tree_repr': tree_repr,
                'visual_graph': visual_graph,
                'factor_name': factor_family.__class__.__name__,
                'params': [serialize_param_meta(param) for param in factor_family.params],
                'desc': getattr(factor_family, 'desc', '') or '',
                'description': getattr(factor_family, 'description', '') or '',
            })
        except Exception as exc:
            return jsonify({
                'success': True,
                'valid': False,
                'error': f'因子加载失败: {str(exc)}',
                'tree_repr': '',
            })

    source_code = (data.get('source_code') or '').strip()
    factor_id = (data.get('factor_id') or '').strip()
    owner_username = (data.get('owner_username') or username or '').strip()

    if not source_code and factor_id:
        if not can_view_user_scope(username, owner_username):
            return jsonify({'success': True, 'valid': False, 'error': '无权查看该用户因子'})
        loaded_source = load_factor_source(owner_username, factor_id) or ''
        source_code = strip_factor_meta(loaded_source) if loaded_source else ''

    if not source_code:
        return jsonify({'success': True, 'valid': False, 'error': '源码不能为空'})

    try:
        import importlib.util
        import re
        import tempfile
        import os as _os

        chinese_name = (data.get('chinese_name') or '').strip()
        description = (data.get('description') or '').strip()
        full_source = assemble_factor_source(source_code, chinese_name, description)

        class_match = re.search(r'^\s*class\s+(\w+)\s*\(', full_source, re.MULTILINE)
        class_name = class_match.group(1) if class_match else 'ValidateFactor'

        tmpdir = tempfile.mkdtemp(prefix='cf_validate_')
        tmpfile = _os.path.join(tmpdir, f'{class_name}.py')
        try:
            with open(tmpfile, 'w', encoding='utf-8') as file:
                file.write(full_source)

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

            return jsonify({
                'success': True,
                'valid': True,
                'error': None,
                'tree_repr': tree_repr,
                'visual_graph': visual_graph,
                'factor_name': factor_cls.__name__,
                'params': [serialize_param_meta(param) for param in factor_family.params],
                'desc': getattr(factor_family, 'desc', '') or '',
                'description': getattr(factor_family, 'description', '') or '',
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
            'error': f'{type(exc).__name__}: {str(exc)}',
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
        from server.services.sqlite.factor_source_settings import load_factor_source_root
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

    from server.services.sqlite.factor_source_settings import save_factor_source_root
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
    result = sync_factor_workspace(username)
    return jsonify({'success': True, **result})


@cf_bp.route('/api/workspace/push', methods=['POST'])
@login_required
def api_push_workspace():
    username = current_user()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    result = push_factor_workspace(username, allow_public_write=is_super_admin_account(get_account(username)))
    return jsonify({'success': True, **result})


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
