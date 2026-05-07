"""
自定义因子模块

提供：
  - 用户自定义因子的 CRUD API
  - 因子表达式（func_expr）校验
  - 公共因子与自定义因子的区分

存储路径：data/users/{username}/custom_factors/
每个自定义因子存为一个 JSON 文件，文件名 = factor_id.json
"""

import os
import json as _json
import time
import uuid
import traceback
from flask import Blueprint, request, jsonify, render_template

from server.shared import (
    login_required, _current_user, _user_data_dir,
    _factor_family_cache_lock, get_factor_family_instance,
)
from tools.factors import FactorFamily

cf_bp = Blueprint('custom_factors', __name__, url_prefix='/custom-factors')

# ── 常量 ──────────────────────────────────────────────────────────────────────

def _cf_dir(username: str) -> str:
    d = os.path.join(_user_data_dir(username), 'custom_factors')
    os.makedirs(d, exist_ok=True)
    return d


def _factor_path(username: str, factor_id: str) -> str:
    return os.path.join(_cf_dir(username), f'{factor_id}.json')


def _load_factor(username: str, factor_id: str) -> dict | None:
    path = _factor_path(username, factor_id)
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return _json.load(f)


def _save_factor(username: str, factor_id: str, data: dict):
    path = _factor_path(username, factor_id)
    with open(path, 'w', encoding='utf-8') as f:
        _json.dump(data, f, ensure_ascii=False, indent=2)


def _delete_factor_file(username: str, factor_id: str) -> bool:
    path = _factor_path(username, factor_id)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def _list_custom_factors(username: str) -> list:
    """列出用户的所有自定义因子，返回按更新时间降序排列的列表。"""
    d = _cf_dir(username)
    factors = []
    if not os.path.exists(d):
        return factors
    for fname in os.listdir(d):
        if not fname.endswith('.json'):
            continue
        factor_id = fname[:-5]  # remove .json
        try:
            data = _load_factor(username, factor_id)
            if data:
                data['id'] = factor_id
                factors.append(data)
        except Exception:
            pass
    factors.sort(key=lambda f: f.get('updated_at', ''), reverse=True)
    return factors


def _list_public_factors() -> list:
    """列出所有公共因子（Factors/ 目录下的 FactorFamily 子类）。"""
    factors_dir = os.path.join(os.getcwd(), 'Factors')
    result = []
    if not os.path.exists(factors_dir):
        return result
    for fname in sorted(os.listdir(factors_dir)):
        if not fname.endswith('.py') or fname.startswith('__'):
            continue
        name = os.path.splitext(fname)[0]
        try:
            ff = get_factor_family_instance(name)
            result.append({
                'id': name,
                'name': name,
                'category': ff.__class__.__bases__[0].__name__ if ff.__class__.__bases__ else 'FactorFamily',
                'chinese_name': getattr(ff, 'desc', '') or getattr(ff, 'chinese_name', '') or '',
                'description': getattr(ff, 'description', '') or '',
                'params': [
                    {'alias': p.alias, 'name': getattr(p, 'name', p.alias), 'default': _serialize_default(p)}
                    for p in ff.params
                ],
                'is_public': True,
            })
        except Exception:
            result.append({
                'id': name,
                'name': name,
                'chinese_name': '',
                'description': '',
                'params': [],
                'is_public': True,
                'load_error': True,
            })
    return result


def _serialize_default(param):
    """序列化参数的默认值，处理 Timedelta / Timestamp 等特殊类型。"""
    try:
        dv = param.default
    except Exception:
        return None
    if dv is None:
        return None
    import pandas as pd
    if isinstance(dv, pd.Timedelta):
        return str(dv)
    if isinstance(dv, pd.Timestamp):
        return dv.strftime('%Y-%m-%d')
    if isinstance(dv, (int, float, str, bool)):
        return dv
    return str(dv)


# ── 公共因子只读详情 ──────────────────────────────────────────────────────────

def _get_public_factor_detail(factor_name: str) -> dict | None:
    """获取公共因子的详细信息（包括 available_params 列表）。"""
    try:
        ff = get_factor_family_instance(factor_name)
        return {
            'id': factor_name,
            'name': factor_name,
            'chinese_name': getattr(ff, 'desc', '') or getattr(ff, 'chinese_name', '') or '',
            'description': getattr(ff, 'description', '') or '',
            'params': [
                {
                    'alias': p.alias,
                    'name': getattr(p, 'name', p.alias),
                    'default': _serialize_default(p),
                    'type': type(p).__name__,
                }
                for p in ff.params
            ],
            'is_public': True,
        }
    except Exception:
        return None


# ═════════════════════════════════════════════════════════════════════════════
# 页面路由
# ═════════════════════════════════════════════════════════════════════════════

@cf_bp.route('/editor', methods=['GET'])
@login_required
def editor_page():
    """自定义因子编辑器页面。"""
    username = _current_user()
    return render_template('custom_factor_editor.html', username=username)


# ═════════════════════════════════════════════════════════════════════════════
# API 路由 — 因子列表
# ═════════════════════════════════════════════════════════════════════════════

@cf_bp.route('/api/list', methods=['GET'])
@login_required
def api_list_factors():
    """
    返回用户的所有因子：公共因子 + 自定义因子。

    响应：
    {
        "success": true,
        "public_factors": [...],   // 公共因子（只读）
        "custom_factors": [...]    // 用户自定义因子
    }
    """
    username = _current_user()
    public = _list_public_factors()
    custom = _list_custom_factors(username)
    return jsonify({
        'success': True,
        'public_factors': public,
        'custom_factors': custom,
    })


@cf_bp.route('/api/public-factor/<factor_name>', methods=['GET'])
@login_required
def api_public_factor_detail(factor_name):
    """获取公共因子的详细信息。"""
    detail = _get_public_factor_detail(factor_name)
    if detail is None:
        return jsonify({'success': False, 'error': f'公共因子 "{factor_name}" 不存在'}), 404
    return jsonify({'success': True, 'factor': detail})


# ═════════════════════════════════════════════════════════════════════════════
# API 路由 — 自定义因子 CRUD
# ═════════════════════════════════════════════════════════════════════════════

@cf_bp.route('/api/create', methods=['POST'])
@login_required
def api_create_factor():
    """
    创建一个新的自定义因子。

    请求体：
    {
        "name": "MyMomentum",          // 因子英文名（唯一标识，同 Factors/ 下模块名规则）
        "chinese_name": "我的动量因子",  // 中文名称
        "description": "...",           // Markdown 格式描述
        "category": "自编",              // 分类（可选）
        "func_expr": "P.delta('$F') / P.shift('$F')",  // 因子表达式
        "params": [                     // 自定义参数定义
            {"alias": "$P", "name": "价格列", "type": "DataColumn", "default": "CA"},
            {"alias": "$F", "name": "窗口", "type": "Timedelta", "default": "5d"}
        ],
        "base_on": "MmRet"              // 可选：基于哪个公共因子创建的
    }

    响应：
    {
        "success": true,
        "factor": { "id": "...", ... }
    }
    """
    username = _current_user()
    data = request.get_json(silent=True) or {}

    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': '因子名称不能为空'}), 400

    # 检查是否与公共因子重名
    public_names = {f['name'] for f in _list_public_factors()}
    if name in public_names:
        return jsonify({'success': False, 'error': f'因子名称 "{name}" 与公共因子重名，请使用其他名称'}), 400

    # 检查是否与已有自定义因子重名
    existing = _list_custom_factors(username)
    existing_names = {f['name'] for f in existing}
    if name in existing_names:
        return jsonify({'success': False, 'error': f'您已有同名自定义因子 "{name}"，请使用其他名称'}), 400

    factor_id = uuid.uuid4().hex[:12]
    now = time.strftime('%Y-%m-%d %H:%M:%S')

    factor_data = {
        'name': name,
        'chinese_name': (data.get('chinese_name') or '').strip(),
        'description': (data.get('description') or '').strip(),
        'category': (data.get('category') or '自编').strip(),
        'func_expr': (data.get('func_expr') or '').strip(),
        'params': data.get('params') or [],
        'base_on': (data.get('base_on') or '').strip(),
        'created_at': now,
        'updated_at': now,
        'is_public': False,
    }

    _save_factor(username, factor_id, factor_data)
    factor_data['id'] = factor_id

    return jsonify({'success': True, 'factor': factor_data})


@cf_bp.route('/api/update/<factor_id>', methods=['POST'])
@login_required
def api_update_factor(factor_id):
    """
    更新自定义因子。

    请求体包含要更新的字段（部分更新即可）。
    """
    username = _current_user()
    existing = _load_factor(username, factor_id)
    if existing is None:
        return jsonify({'success': False, 'error': '因子不存在'}), 404

    data = request.get_json(silent=True) or {}

    updatable_fields = ['name', 'chinese_name', 'description', 'category', 'func_expr', 'params', 'base_on']
    for field in updatable_fields:
        if field in data:
            existing[field] = data[field]

    existing['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')

    _save_factor(username, factor_id, existing)
    existing['id'] = factor_id

    return jsonify({'success': True, 'factor': existing})


@cf_bp.route('/api/delete/<factor_id>', methods=['POST'])
@login_required
def api_delete_factor(factor_id):
    """删除自定义因子。"""
    username = _current_user()
    existing = _load_factor(username, factor_id)
    if existing is None:
        return jsonify({'success': False, 'error': '因子不存在'}), 404

    _delete_factor_file(username, factor_id)
    return jsonify({'success': True, 'message': f'因子 "{existing["name"]}" 已删除'})


@cf_bp.route('/api/get/<factor_id>', methods=['GET'])
@login_required
def api_get_factor(factor_id):
    """获取单个自定义因子的详情。"""
    username = _current_user()
    factor = _load_factor(username, factor_id)
    if factor is None:
        return jsonify({'success': False, 'error': '因子不存在'}), 404
    factor['id'] = factor_id
    return jsonify({'success': True, 'factor': factor})


# ═════════════════════════════════════════════════════════════════════════════
# API 路由 — 因子校验
# ═════════════════════════════════════════════════════════════════════════════

@cf_bp.route('/api/validate', methods=['POST'])
@login_required
def api_validate_expr():
    """
    校验 func_expr 是否合法。

    请求体：
    {
        "func_expr": "P.delta('$F') / P.shift('$F')",
        "params": [...]
    }

    响应：
    {
        "success": true,
        "valid": true,
        "error": null
    }
    """
    data = request.get_json(silent=True) or {}
    func_expr = (data.get('func_expr') or '').strip()

    if not func_expr:
        return jsonify({'success': True, 'valid': False, 'error': '表达式不能为空'})

    try:
        # 简单校验：尝试解析 Python 语法
        import ast
        ast.parse(func_expr)
    except SyntaxError as e:
        return jsonify({'success': True, 'valid': False, 'error': f'语法错误: {e.msg}'})

    # TODO: 更深入的因子表达式语义校验（执行表达式树构建）
    # 目前只做语法层面校验
    return jsonify({'success': True, 'valid': True, 'error': None})


# ═════════════════════════════════════════════════════════════════════════════
# API 路由 — 参数模板（可选：保存/加载因子参数配置）
# ═════════════════════════════════════════════════════════════════════════════

@cf_bp.route('/api/params/preset', methods=['GET'])
@login_required
def api_params_preset():
    """
    返回可用的预定义参数类型列表，供编辑器下拉选择。
    """
    presets = [
        {'type': 'DataColumn', 'label': '数据列', 'desc': '选择价格列（如 CLOSE、OPEN 等）', 'example_alias': '$P', 'example_default': 'CA'},
        {'type': 'Timedelta', 'label': '时间窗口', 'desc': '时间长度（如 5d、30min）', 'example_alias': '$F', 'example_default': '5d'},
        {'type': 'int', 'label': '整数', 'desc': '整数参数（如回看周期数）', 'example_alias': '$N', 'example_default': 20},
        {'type': 'float', 'label': '浮点数', 'desc': '小数参数（如阈值）', 'example_alias': '$T', 'example_default': 0.5},
        {'type': 'bool', 'label': '布尔值', 'desc': '开关参数（True/False）', 'example_alias': '$B', 'example_default': False},
        {'type': 'str', 'label': '字符串', 'desc': '字符串参数', 'example_alias': '$S', 'example_default': 'default'},
    ]
    return jsonify({'success': True, 'presets': presets})
