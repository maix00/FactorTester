"""
自定义因子模块

提供：
  - 用户自定义因子的 CRUD API
  - 因子表达式（factor_expr）校验
  - 公共因子与自定义因子的区分

存储路径：data/users/{username}/custom_factors/
每个自定义因子存为一个 .py 文件，文件名 = factor_id.py
"""

import os
import json as _json
import time
import uuid
import traceback
from flask import Blueprint, request, jsonify, render_template

from server.shared import (
    login_required, _current_user, _user_data_dir, _load_accounts,
    _factor_family_cache_lock, get_factor_family_instance,
    invalidate_custom_factor_cache,
)
from tools.factors import FactorFamily

cf_bp = Blueprint('custom_factors', __name__, url_prefix='/custom-factors')

# ── 常量 ──────────────────────────────────────────────────────────────────────

def _cf_dir(username: str) -> str:
    d = os.path.join(_user_data_dir(username), 'custom_factors')
    os.makedirs(d, exist_ok=True)
    return d


def _factor_path(username: str, factor_id: str) -> str:
    return os.path.join(_cf_dir(username), f'{factor_id}.py')


def _load_factor(username: str, factor_id: str) -> str | None:
    """加载自定义因子的 .py 源码文件，返回完整 Python 源码字符串。"""
    path = _factor_path(username, factor_id)
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def _save_factor(username: str, factor_id: str, source_code: str):
    """保存自定义因子的完整 .py 源码文件。"""
    path = _factor_path(username, factor_id)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(source_code)


def _delete_factor_file(username: str, factor_id: str) -> bool:
    path = _factor_path(username, factor_id)
    if os.path.exists(path):
        os.remove(path)
        return True
    # 兼容旧的 .json 文件清理
    old_path = os.path.join(_cf_dir(username), f'{factor_id}.json')
    if os.path.exists(old_path):
        os.remove(old_path)
    return False


def _list_custom_factors(username: str) -> list:
    """列出用户的所有自定义因子，返回按更新时间降序排列的列表。

    从 .py 文件 import，提取 class 的 desc/description/params 元信息。
    """
    d = _cf_dir(username)
    factors = []
    if not os.path.exists(d):
        return factors
    for fname in sorted(os.listdir(d), reverse=True):
        if not fname.endswith('.py'):
            continue
        factor_id = os.path.splitext(fname)[0]
        mtime = os.path.getmtime(os.path.join(d, fname))
        updated_at = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))

        try:
            # 用 importlib 加载 .py，获取 FactorFamily 子类
            import importlib.util
            module_name = f'_cf_{username}_{factor_id}'
            spec = importlib.util.spec_from_file_location(module_name, os.path.join(d, fname))
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # 找到模块中的 FactorFamily 子类
            from tools.factors import FactorFamily
            factor_cls = None
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if isinstance(obj, type) and issubclass(obj, FactorFamily) and obj is not FactorFamily:
                    factor_cls = obj
                    break
            if factor_cls is None:
                continue

            ff = factor_cls()
            # 因子家族
            bases = factor_cls.__bases__
            family = 'FactorFamily'
            for b in bases:
                if b is not FactorFamily and issubclass(b, FactorFamily):
                    family = b.__name__
                    break
            factors.append({
                'id': factor_id,
                'name': factor_cls.__name__,
                'category': getattr(ff, 'category', '') or '自编',
                'factor_family': family,
                'chinese_name': getattr(ff, 'desc', '') or '',
                'description': getattr(ff, 'description', '') or '',
                'math_expr': getattr(ff, 'math_expr', '') or '',
                'params': [
                    {'alias': p.alias, 'name': p.alias, 'default_value': _serialize_default(p)}
                    for p in ff.params
                ],
                'is_public': False,
                'updated_at': updated_at,
            })
        except Exception:
            # 加载失败时仍然返回基本信息（从文件名推断）
            factors.append({
                'id': factor_id,
                'name': factor_id,
                'category': '自编',
                'factor_family': 'FactorFamily',
                'chinese_name': '',
                'description': '',
                'params': [],
                'is_public': False,
                'updated_at': updated_at,
                'load_error': True,
            })
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
            # 因子家族：取父类链中紧邻 FactorFamily 之上的类名（如果有中间家族类），
            # 否则用 FactorFamily 作为默认家族
            bases = ff.__class__.__bases__
            family = 'FactorFamily'
            for b in bases:
                if b is not FactorFamily and issubclass(b, FactorFamily):
                    family = b.__name__
                    break
            mtime = os.path.getmtime(os.path.join(factors_dir, fname))
            updated_at = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))
            result.append({
                'id': name,
                'name': name,
                'category': getattr(ff, 'category', '') or family,
                'factor_family': family,
                'chinese_name': getattr(ff, 'desc', '') or getattr(ff, 'chinese_name', '') or '',
                'description': getattr(ff, 'description', '') or '',
                'math_expr': getattr(ff, 'math_expr', '') or '',
                'params': [
                    {'alias': p.alias, 'name': p.alias, 'default_value': _serialize_default(p)}
                    for p in ff.params
                ],
                'is_public': True,
                'updated_at': updated_at,
            })
        except Exception:
            result.append({
                'id': name,
                'name': name,
                'category': '',
                'factor_family': 'FactorFamily',
                'chinese_name': '',
                'description': '',
                'params': [],
                'is_public': True,
                'updated_at': '',
                'load_error': True,
            })
    return result


def _serialize_default(param):
    """序列化参数的默认值，处理 Timedelta / Timestamp 等特殊类型。"""
    try:
        dv = param.default_value
        try:
            dv = param.get_value_alias(dv)
        except Exception:
            pass
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


def _parse_class_meta(source_code: str) -> dict:
    """从 Python 源码中提取 class 元信息：name, chinese_name(desc), description, category。"""
    import re
    result = {'name': '', 'chinese_name': '', 'description': '', 'category': ''}

    # 提取 class 名称
    class_match = re.search(r'^\s*class\s+(\w+)\s*\(', source_code, re.MULTILINE)
    if class_match:
        result['name'] = class_match.group(1)

    # 提取 desc = '...'
    desc_match = re.search(r"""^\s*desc\s*=\s*['\"]([^'\"]*)['\"]""", source_code, re.MULTILINE)
    if desc_match:
        result['chinese_name'] = desc_match.group(1)

    # 提取 description = """...""" 或 '''...'''
    desc_long_match = re.search(
        r'^\s*description\s*=\s*("""|\'\'\')(.*?)\1',
        source_code, re.MULTILINE | re.DOTALL
    )
    if not desc_long_match:
        # 尝试单行 description
        desc_long_match = re.search(r"""^\s*description\s*=\s*['\"]([^'\"]*)['\"]""", source_code, re.MULTILINE)
    if desc_long_match:
        result['description'] = desc_long_match.group(2) if desc_long_match.lastindex >= 2 else desc_long_match.group(1)

    # 提取 category
    cat_match = re.search(r"""^\s*category\s*=\s*['\"]([^'\"]*)['\"]""", source_code, re.MULTILINE)
    if cat_match:
        result['category'] = cat_match.group(1)

    return result


def _assemble_py(source_code: str, chinese_name: str = '', description: str = '',
                 category: str = '自编') -> str:
    """将用户编写的源码片段拼装为完整的 .py 文件。

    用户 source_code 只需包含 import 行 + class 头部 + factor_expr() 方法体。
    desc / description 由本函数拼入，缩进统一使用 4 空格。
    """
    import re

    lines = source_code.split('\n')

    # ── 收集 import 行（class 定义之前的所有行） ──
    import_lines = []
    class_start = 0
    for i, line in enumerate(lines):
        if re.match(r'^\s*class\s+\w+\s*\(', line):
            class_start = i
            break
        import_lines.append(line)
    for i in range(len(lines)):
        if re.match(r'^\s*class\s+\w+\s*\(', lines[i]):
            class_start = i
            break
    import_lines = lines[:class_start]

    # ── 提取 class 名称 ──
    class_match = re.search(r'^\s*class\s+(\w+)\s*\((.*?)\)\s*$', lines[class_start])
    class_name = class_match.group(1) if class_match else 'MyFactor'
    base_class = class_match.group(2).strip() if class_match else 'FactorFamily'

    # ── 提取 factor_expr 方法体（def factor_expr ... return ...） ──
    # 从 class 行之后的所有行中提取
    body_lines = []
    in_factor_expr = False
    factor_expr_indent = ''
    for line in lines[class_start + 1:]:
        if re.match(r'^\s*(@staticmethod\s*$|def\s+factor_expr\s*\()', line):
            in_factor_expr = True
            factor_expr_indent = line[:len(line) - len(line.lstrip())]
            continue
        if in_factor_expr:
            # 遇到非空行且缩进 <= 方法缩进，说明出了方法体
            stripped = line.strip()
            if stripped:
                line_indent = line[:len(line) - len(line.lstrip())]
                if len(line_indent) <= len(factor_expr_indent):
                    break
                # 跳过已有的 desc / description / category 行
                if re.match(r'^\s*(desc|description|category)\s*=', line):
                    continue
            body_lines.append(line)

    # ── 拼装 ──
    indent = '    '  # class 体内缩进

    parts = []
    # 头部注释
    parts.append(f'# -*- coding: utf-8 -*-')
    parts.append(f'# Custom Factor: {class_name}')
    parts.append('')

    # import 行（不过滤，保持用户手写）
    for il in import_lines:
        parts.append(il)
    # 确保有基础 import
    parts.append('from tools.factors import FactorFamily')
    parts.append('from tools.parameters import WindowParam, DataColumnParam, DateOrTimeParam')
    parts.append('')

    # class 定义
    parts.append(f'class {class_name}({base_class}):')
    if not any(l.strip().startswith('"""') or l.strip().startswith("'''") or l.strip().startswith('#') for l in body_lines[:2]):
        parts.append(f'{indent}"""')
        parts.append(f'{indent}{chinese_name or class_name}')
        parts.append(f'{indent}"""')

    # factor_expr 方法
    parts.append('')
    parts.append(f'{indent}@staticmethod')
    parts.append(f'{indent}def factor_expr():')
    for bl in body_lines:
        parts.append(bl if bl.startswith(indent) else indent + bl)

    # desc
    if chinese_name:
        parts.append('')
        parts.append(f'{indent}desc = {repr(chinese_name)}')

    # description（多行时用三引号）
    if description:
        parts.append('')
        if '\n' in description:
            parts.append(f'{indent}description = """')
            for dl in description.split('\n'):
                parts.append(f'{indent}{dl}')
            parts.append(f'{indent}"""')
        else:
            parts.append(f'{indent}description = {repr(description)}')

    # category
    if category:
        parts.append(f'{indent}category = {repr(category)}')

    parts.append('')

    return '\n'.join(parts)


def _strip_meta(source_code: str) -> str:
    """从完整 .py 源码中移除 desc/description/category 类属性行。

    返回编辑区用的纯源码（import + class + factor_expr），
    不含用户通过右侧表单编辑的元信息。
    正确处理 description = \"\"\"...\"\"\" 多行块。
    """
    import re
    lines = source_code.split('\n')
    stripped = []
    in_multiline_desc = False
    for line in lines:
        # 进入多行 description =
        if re.match(r'^\s*description\s*=\s*("""|\'\'\')', line):
            in_multiline_desc = True
            # 如果同行闭合（单行三引号），不算多行
            if line.count('"""') + line.count("'''") >= 2:
                in_multiline_desc = False
            continue
        if in_multiline_desc:
            if '"""' in line or "'''" in line:
                in_multiline_desc = False
            continue
        # 跳过单行 desc / description / category
        if re.match(r'^\s*(desc|description|category)\s*=', line):
            continue
        stripped.append(line)
    return '\n'.join(stripped)


# ── 公共因子只读详情 ──────────────────────────────────────────────────────────

def _get_public_factor_detail(factor_name: str) -> dict | None:
    """获取公共因子的详细信息（包括完整源码和 tree_repr）。"""
    try:
        ff = get_factor_family_instance(factor_name)

        # 读取对应的 .py 源文件，返回完整源码
        factors_dir = os.path.join(os.getcwd(), 'Factors')
        src_path = os.path.join(factors_dir, f'{factor_name}.py')
        source_code = ''
        if os.path.exists(src_path):
            with open(src_path, 'r', encoding='utf-8') as f:
                source_code = f.read()

        # 获取表达式树的 tree_repr
        tree_repr = ''
        try:
            if ff.expr is not None:
                tree_repr = ff.expr.tree_repr()
        except Exception:
            pass

        return {
            'id': factor_name,
            'name': factor_name,
            'chinese_name': getattr(ff, 'desc', '') or getattr(ff, 'chinese_name', '') or '',
            'description': getattr(ff, 'description', '') or '',
            'source_code': _strip_meta(source_code),
            'tree_repr': tree_repr,
            'params': [
                {
                    'alias': p.alias,
                    'name': p.alias,
                    'default_value': _serialize_default(p),
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
    # 检查是否管理员
    is_admin = False
    if username:
        accts = _load_accounts()
        for a in accts:
            if a.get('username') == username and a.get('is_admin'):
                is_admin = True
                break
    return jsonify({
        'success': True,
        'public_factors': public,
        'custom_factors': custom,
        'is_admin': is_admin,
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
        "source_code": "完整 Python class 源码",   // 必填：因子源码
        "chinese_name": "我的动量因子",             // 可选：中文名称 → desc
        "description": "...",                      // 可选：Markdown 描述
        "category": "自编"                          // 可选：分类
    }

    响应：
    {
        "success": true,
        "factor": { "id": "...", ... }
    }
    """
    username = _current_user()
    data = request.get_json(silent=True) or {}

    source_code = (data.get('source_code') or '').strip()
    if not source_code:
        return jsonify({'success': False, 'error': '源码不能为空'}), 400

    # 从源码中解析 class 名称
    import re
    class_match = re.search(r'^\s*class\s+(\w+)\s*\(', source_code, re.MULTILINE)
    if not class_match:
        return jsonify({'success': False, 'error': '源码中未找到 class 定义'}), 400
    name = class_match.group(1)

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

    # 注入 desc 和 description（如果用户在右侧表单填写了）
    chinese_name = (data.get('chinese_name') or '').strip()
    description = (data.get('description') or '').strip()
    category = (data.get('category') or '自编').strip()

    # 用 _assemble_py 拼装完整 .py 文件（缩进由后端统一控制）
    full_source = _assemble_py(source_code, chinese_name, description, category)

    _save_factor(username, factor_id, full_source)

    # 返回因子信息
    return jsonify({
        'success': True,
        'factor': {
            'id': factor_id,
            'name': name,
            'chinese_name': chinese_name,
            'description': description,
            'category': (data.get('category') or '自编').strip(),
            'is_public': False,
        }
    })


@cf_bp.route('/api/update/<factor_id>', methods=['POST'])
@login_required
def api_update_factor(factor_id):
    """
    更新自定义因子。

    请求体：
    {
        "source_code": "更新后的源码片段",   // 编辑区的源码（不含 desc/description）
        "chinese_name": "...",             // 可选
        "description": "...",              // 可选
        "category": "..."                  // 可选
    }
    """
    username = _current_user()
    existing_source = _load_factor(username, factor_id)
    if existing_source is None:
        return jsonify({'success': False, 'error': '因子不存在'}), 404

    data = request.get_json(silent=True) or {}

    # 从已保存的文件中提取旧 name
    old_meta = _parse_class_meta(existing_source)
    old_name = old_meta.get('name', '')

    source_code = (data.get('source_code') or '').strip()
    chinese_name = (data.get('chinese_name') or '').strip()
    description = (data.get('description') or '').strip()
    category = (data.get('category') or old_meta.get('category', '自编')).strip()

    if source_code:
        # 检查 class 名是否变更，是否冲突
        import re
        class_match = re.search(r'^\s*class\s+(\w+)\s*\(', source_code, re.MULTILINE)
        new_name = class_match.group(1) if class_match else old_name
        if new_name != old_name:
            public_names = {f['name'] for f in _list_public_factors()}
            if new_name in public_names:
                return jsonify({'success': False, 'error': f'因子名称 "{new_name}" 与公共因子重名'}), 400
            existing_list = _list_custom_factors(username)
            existing_names = {f['name'] for f in existing_list if f['id'] != factor_id}
            if new_name in existing_names:
                return jsonify({'success': False, 'error': f'您已有同名自定义因子 "{new_name}"'}), 400

        full_source = _assemble_py(source_code, chinese_name or old_meta.get('chinese_name', ''),
                                   description or old_meta.get('description', ''), category)
    else:
        # 只更新元信息，不更新源码
        old_editor_source = _strip_meta(existing_source)
        full_source = _assemble_py(old_editor_source, chinese_name or old_meta.get('chinese_name', ''),
                                   description or old_meta.get('description', ''), category)

    _save_factor(username, factor_id, full_source)

    # 清除缓存
    invalidate_custom_factor_cache(username, factor_id)
    if old_name and old_name != (new_name if source_code else old_name):
        with _factor_family_cache_lock:
            _factor_family_cache.pop(old_name, None)

    new_meta = _parse_class_meta(full_source)
    return jsonify({
        'success': True,
        'factor': {
            'id': factor_id,
            'name': new_meta.get('name', old_name),
            'chinese_name': new_meta.get('chinese_name', ''),
            'description': new_meta.get('description', ''),
            'category': new_meta.get('category', '自编'),
            'is_public': False,
        }
    })


@cf_bp.route('/api/delete/<factor_id>', methods=['POST'])
@login_required
def api_delete_factor(factor_id):
    """删除自定义因子。"""
    username = _current_user()
    existing_source = _load_factor(username, factor_id)
    if existing_source is None:
        return jsonify({'success': False, 'error': '因子不存在'}), 404

    old_meta = _parse_class_meta(existing_source)
    old_name = old_meta.get('name', '')
    _delete_factor_file(username, factor_id)

    # 清除缓存
    invalidate_custom_factor_cache(username, factor_id)
    if old_name:
        with _factor_family_cache_lock:
            _factor_family_cache.pop(old_name, None)

    return jsonify({'success': True, 'message': f'因子 "{old_name}" 已删除'})


@cf_bp.route('/api/get/<factor_id>', methods=['GET'])
@login_required
def api_get_factor(factor_id):
    """获取单个自定义因子的详情。

    返回：
    - source_code: 剥离 desc/description 后的纯源码（给左侧编辑器）
    - chinese_name / description: 从文件中解析出的元信息（给右侧面板）
    """
    username = _current_user()
    source = _load_factor(username, factor_id)
    if source is None:
        return jsonify({'success': False, 'error': '因子不存在'}), 404

    meta = _parse_class_meta(source)
    return jsonify({
        'success': True,
        'factor': {
            'id': factor_id,
            'name': meta.get('name', ''),
            'chinese_name': meta.get('chinese_name', ''),
            'description': meta.get('description', ''),
            'category': meta.get('category', '自编'),
            'source_code': _strip_meta(source),
            'is_public': False,
        }
    })


# ═════════════════════════════════════════════════════════════════════════════
# API 路由 — 因子校验
# ═════════════════════════════════════════════════════════════════════════════

@cf_bp.route('/api/validate', methods=['POST'])
@login_required
def api_validate_expr():
    """
    校验源码是否合法，并返回表达式树的 tree_repr。

    请求体：
    {
        "source_code": "完整 Python class 源码片段",   // 自定义因子：编辑区的源码
        "factor_name": "MmRSI",                      // 公共因子：因子名
        "is_public": true,                           // 是否为公共因子
        "factor_id": "abc123"                        // 可选：已保存的自定义因子 ID
    }

    响应：
    {
        "success": true,
        "valid": true,
        "error": null,
        "tree_repr": "..."      // 表达式树文本
    }
    """
    data = request.get_json(silent=True) or {}
    username = _current_user()

    # ── 公共因子：从已加载的 FactorFamily 获取 tree_repr ──
    if data.get('is_public') and data.get('factor_name'):
        factor_name = data['factor_name']
        try:
            ff = get_factor_family_instance(factor_name)
            tree_repr = ''
            if ff.expr is not None:
                tree_repr = ff.expr.tree_repr()
            return jsonify({
                'success': True,
                'valid': True,
                'error': None,
                'tree_repr': tree_repr,
                'desc': getattr(ff, 'desc', '') or '',
                'description': getattr(ff, 'description', '') or '',
            })
        except Exception as e:
            return jsonify({
                'success': True,
                'valid': False,
                'error': f'因子加载失败: {str(e)}',
                'tree_repr': '',
            })

    # ── 自定义因子：编译源码 → exec → 获取 tree_repr ──
    source_code = (data.get('source_code') or '').strip()
    factor_id = (data.get('factor_id') or '').strip()

    if not source_code and factor_id:
        # 从已保存文件加载
        source_code = _load_factor(username, factor_id) or ''

    if not source_code:
        return jsonify({'success': True, 'valid': False, 'error': '源码不能为空'})

    try:
        import importlib.util
        import sys
        import re

        # 拼装完整 .py，用临时模块编译
        chinese_name = (data.get('chinese_name') or '').strip()
        description = (data.get('description') or '').strip()
        full_source = _assemble_py(source_code, chinese_name, description)

        # 提取 class 名
        class_match = re.search(r'^\s*class\s+(\w+)\s*\(', full_source, re.MULTILINE)
        class_name = class_match.group(1) if class_match else 'ValidateFactor'

        # 用临时文件 importlib 加载
        import tempfile, os as _os
        tmpdir = tempfile.mkdtemp(prefix='cf_validate_')
        tmpfile = _os.path.join(tmpdir, f'{class_name}.py')
        try:
            with open(tmpfile, 'w', encoding='utf-8') as f:
                f.write(full_source)

            spec = importlib.util.spec_from_file_location(class_name, tmpfile)
            if spec is None or spec.loader is None:
                return jsonify({'success': True, 'valid': False, 'error': '无法加载源码模块'})

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # 找到 FactorFamily 子类
            from tools.factors import FactorFamily
            factor_cls = None
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if isinstance(obj, type) and issubclass(obj, FactorFamily) and obj is not FactorFamily:
                    factor_cls = obj
                    break
            if factor_cls is None:
                return jsonify({'success': True, 'valid': False, 'error': '源码中未找到 FactorFamily 子类'})

            ff = factor_cls()
            tree_repr = ''
            if ff.expr is not None:
                tree_repr = ff.expr.tree_repr()

            return jsonify({
                'success': True,
                'valid': True,
                'error': None,
                'tree_repr': tree_repr,
                'desc': getattr(ff, 'desc', '') or '',
                'description': getattr(ff, 'description', '') or '',
            })

        finally:
            # 清理临时文件
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    except SyntaxError as e:
        return jsonify({'success': True, 'valid': False, 'error': f'语法错误: {e.msg}'})
    except Exception as e:
        import traceback
        return jsonify({
            'success': True,
            'valid': False,
            'error': f'{type(e).__name__}: {str(e)}',
            'traceback': traceback.format_exc(),
        })


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
