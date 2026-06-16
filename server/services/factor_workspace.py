"""Local factor workspace build and sync helpers."""

from __future__ import annotations

import json
import os
import ast
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from server.services.sqlite.factor_source_store import list_factor_sources
from server.services.sqlite.factor_source_workspace_settings import (
    load_factor_source_workspace_settings,
    save_factor_source_workspace_settings,
)
from tools.tool_docs import scan_tool_files


def _storage():
    from server.modules.custom_factors import storage as factor_storage
    return factor_storage


def _workspace_root(username: str) -> str:
    return _storage().factor_source_root(username)


def _workspace_public_dir(root: str) -> str:
    return os.path.join(root, 'public_factors')


def _workspace_custom_dir(root: str) -> str:
    return os.path.join(root, 'custom_factors')


def _workspace_tools_dir(root: str) -> str:
    return os.path.join(root, 'tools')


def _source_tools_dir() -> str:
    return str(Path(__file__).resolve().parents[2] / 'tools')


_TOOLS_STUB_MODULES = {
    '__init__.py',
    'base/UniqueNameObject.py',
    'parameters/Parameter.py',
    'parameters/DataColumnParam.py',
    'parameters/DataTimeParam.py',
    'parameters/WindowParam.py',
    'parameters/__init__.py',
    'data/types/DataColumn.py',
    'data/types/DataFreq.py',
    'data/types/DataTime.py',
    'data/types/__init__.py',
    'data/views/ProductDataView.py',
    'data/views/__init__.py',
    'factors/Parameters.py',
    'factors/FactorExpr.py',
    'factors/Factors.py',
    'factors/FactorRunResult.py',
    'factors/FactorFamily.py',
    'factors/__init__.py',
    'factors/expr/__init__.py',
    'factors/expr/composite.py',
    'factors/expr/conditional.py',
    'factors/expr/core.py',
    'factors/expr/cross_sectional.py',
    'factors/expr/leaf.py',
    'factors/expr/operands.py',
    'factors/expr/rolling.py',
    'factors/expr/shift.py',
    'factors/expr/signal_align.py',
    'factors/expr/term_structure.py',
    'factors/expr/visual_groups.py',
}


def _git_binary_available() -> bool:
    return shutil.which('git') is not None


def _run_git(root: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['git', '-C', root, *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _git_repo_root(root: str) -> str | None:
    if not _git_binary_available():
        return None
    result = _run_git(root, 'rev-parse', '--show-toplevel')
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _git_current_branch(root: str) -> str | None:
    if not _git_binary_available():
        return None
    result = _run_git(root, 'branch', '--show-current')
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None


def _git_branch_names(root: str) -> list[str]:
    if not _git_binary_available():
        return []
    result = _run_git(root, 'branch', '--format=%(refname:short)')
    if result.returncode != 0:
        return []
    branches = [line.strip().lstrip('* ').strip() for line in result.stdout.splitlines()]
    return [branch for branch in branches if branch]


def _git_checkout_branch(root: str, branch: str) -> bool:
    branch = str(branch or '').strip()
    if not branch or not _git_binary_available() or not os.path.isdir(os.path.join(root, '.git')):
        return False
    current_branch = _git_current_branch(root)
    if current_branch == branch:
        return False
    result = _run_git(root, 'checkout', '-B', branch)
    if result.returncode != 0:
        return False
    return True


def _ensure_git_workspace(root: str, username: str) -> dict[str, Any]:
    if not _git_binary_available():
        save_factor_source_workspace_settings(
            username,
            git_enabled=False,
            git_repo_root=None,
            auto_sync_branch='',
            force_sync_branch='',
        )
        return {
            'git_enabled': False,
            'git_repo_root': '',
            'git_current_branch': '',
            'git_auto_sync_branch': '',
            'git_force_sync_branch': '',
            'git_branches': [],
        }

    git_dir = os.path.join(root, '.git')
    if not os.path.exists(git_dir):
        init = subprocess.run(
            ['git', 'init', '-b', 'main', root],
            check=False,
            capture_output=True,
            text=True,
        )
        if init.returncode != 0:
            subprocess.run(['git', 'init', root], check=False, capture_output=True, text=True)
            subprocess.run(['git', '-C', root, 'checkout', '-B', 'main'], check=False, capture_output=True, text=True)

    repo_root = _git_repo_root(root) or root
    current_branch = _git_current_branch(root) or 'main'
    branches = _git_branch_names(root)
    if current_branch not in branches:
        branches = [current_branch] + [branch for branch in branches if branch != current_branch]
    existing = load_factor_source_workspace_settings(username) or {}
    auto_branch = str(existing.get('auto_sync_branch') or current_branch or 'main')
    force_branch = str(existing.get('force_sync_branch') or auto_branch)
    save_factor_source_workspace_settings(
        username,
        git_enabled=True,
        git_repo_root=repo_root,
        auto_sync_branch=auto_branch,
        force_sync_branch=force_branch,
    )
    return {
        'git_enabled': True,
        'git_repo_root': repo_root,
        'git_current_branch': current_branch,
        'git_auto_sync_branch': auto_branch,
        'git_force_sync_branch': force_branch,
        'git_branches': branches,
    }


def _resolve_workspace_branch(username: str, branch_mode: str) -> str:
    settings = load_factor_source_workspace_settings(username) or {}
    auto_branch = str(settings.get('auto_sync_branch') or '').strip()
    force_branch = str(settings.get('force_sync_branch') or '').strip()
    if branch_mode == 'force' and force_branch:
        return force_branch
    if auto_branch:
        return auto_branch
    return force_branch


def _apply_workspace_git_branch(root: str, username: str, branch_mode: str) -> str:
    branch = _resolve_workspace_branch(username, branch_mode)
    if branch:
        _git_checkout_branch(root, branch)
    return branch


def _ensure_workspace_layout(root: str) -> None:
    Path(root).mkdir(parents=True, exist_ok=True)
    Path(_workspace_public_dir(root)).mkdir(parents=True, exist_ok=True)
    Path(_workspace_custom_dir(root)).mkdir(parents=True, exist_ok=True)
    Path(_workspace_tools_dir(root)).mkdir(parents=True, exist_ok=True)
    Path(os.path.join(root, '.factor_workspace')).mkdir(parents=True, exist_ok=True)
    Path(os.path.join(root, '.vscode')).mkdir(parents=True, exist_ok=True)


def _write_text_if_changed(path: str, content: str) -> bool:
    existing = None
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as file:
            existing = file.read()
    if existing == content:
        return False
    Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as file:
        file.write(content)
    return True


def _write_json(path: str, payload: dict[str, Any]) -> bool:
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return _write_text_if_changed(path, content + '\n')


def _annotation_to_source(node: ast.AST | None) -> str:
    if node is None:
        return 'Any'
    try:
        return ast.unparse(node)
    except Exception:
        return 'Any'


def _format_arguments(args: ast.arguments) -> str:
    parts: list[str] = []
    posonly = list(args.posonlyargs)
    normal = list(args.args)
    defaults = [None] * (len(posonly) + len(normal) - len(args.defaults)) + list(args.defaults)
    for index, arg in enumerate(posonly + normal):
        piece = arg.arg
        if arg.annotation is not None:
            piece += f': {_annotation_to_source(arg.annotation)}'
        default = defaults[index] if index < len(defaults) else None
        if default is not None:
            piece += ' = ...'
        parts.append(piece)
        if posonly and index + 1 == len(posonly):
            parts.append('/')
    if args.vararg is not None:
        piece = f'*{args.vararg.arg}'
        if args.vararg.annotation is not None:
            piece += f': {_annotation_to_source(args.vararg.annotation)}'
        parts.append(piece)
    elif args.kwonlyargs:
        parts.append('*')
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        piece = arg.arg
        if arg.annotation is not None:
            piece += f': {_annotation_to_source(arg.annotation)}'
        if default is not None:
            piece += ' = ...'
        parts.append(piece)
    if args.kwarg is not None:
        piece = f'**{args.kwarg.arg}'
        if args.kwarg.annotation is not None:
            piece += f': {_annotation_to_source(args.kwarg.annotation)}'
        parts.append(piece)
    return ', '.join(parts)


def _decorator_to_source(decorator: ast.expr) -> str | None:
    if isinstance(decorator, ast.Name) and decorator.id in {'classmethod', 'staticmethod', 'property'}:
        return decorator.id
    return None


def _comment_block_before(lines: list[str], lineno: int) -> list[str]:
    block: list[str] = []
    idx = lineno - 2
    saw_comment = False
    blank_run = 0
    while idx >= 0:
        stripped = lines[idx].strip()
        if stripped.startswith('#'):
            block.append(lines[idx].rstrip())
            saw_comment = True
            blank_run = 0
        elif stripped == '':
            if saw_comment:
                blank_run += 1
                if blank_run > 1:
                    break
                block.append('')
            elif block:
                block.append('')
        else:
            break
        idx -= 1
    while block and block[-1] == '':
        block.pop()
    block.reverse()
    return block


def _append_comment_block(lines: list[str], comment_block: list[str]) -> None:
    if not comment_block:
        return
    if lines and lines[-1] != '':
        lines.append('')
    lines.extend(comment_block)


def _render_assignment_stub(node: ast.Assign) -> str | None:
    if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
        return None
    target = node.targets[0].id
    if target.startswith('_'):
        return None
    inferred = 'Any'
    if target in {'ReturnFreqParam', 'FactorFreqParam', 'ReverseParam'}:
        inferred = 'Parameter'
    elif target == 'StartCalcPointParam':
        inferred = 'DataTimeParam'
    elif isinstance(node.value, ast.Call):
        func_name = ''
        if isinstance(node.value.func, ast.Name):
            func_name = node.value.func.id
        elif isinstance(node.value.func, ast.Attribute):
            func_name = node.value.func.attr
        if func_name.endswith('_param') or func_name.startswith('get_'):
            inferred = 'Parameter'
    return f'{target}: {inferred} = ...'


def _collect_instance_attrs(class_node: ast.ClassDef) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for node in class_node.body:
        if not isinstance(node, ast.FunctionDef) or node.name != '__init__':
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == 'self'
                        and target.attr not in attrs
                    ):
                        attrs[target.attr] = 'Any'
            elif isinstance(child, ast.AnnAssign):
                target = child.target
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == 'self'
                    and target.attr not in attrs
                ):
                    attrs[target.attr] = _annotation_to_source(child.annotation)
    return attrs


def _render_stub_module(source: str, filename: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return '\n'.join([
            'from __future__ import annotations',
            'from typing import Any',
            '',
            '...',
            '',
        ])

    lines: list[str] = ['from __future__ import annotations', 'from typing import Any']
    source_lines = source.splitlines()

    for node in tree.body:
        comment_block = _comment_block_before(source_lines, getattr(node, 'lineno', 1))
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module_name = node.module if isinstance(node, ast.ImportFrom) else None
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                if module_name and not (
                    module_name == 'typing'
                    or module_name.startswith('typing')
                    or module_name.startswith('tools.factors')
                    or module_name.startswith('tools.parameters')
                    or module_name.startswith('tools.base')
                    or module_name.startswith('tools.data.types')
                    or module_name == 'Settings'
                ):
                    continue
                if module_name == 'tools':
                    continue
                if module_name == 'tools.factors.FactorTester':
                    continue
            if isinstance(node, ast.ImportFrom) and node.module == '__future__':
                continue
            _append_comment_block(lines, comment_block)
            lines.append(ast.unparse(node))
        if isinstance(node, ast.Assign):
            rendered = _render_assignment_stub(node)
            if rendered:
                _append_comment_block(lines, comment_block)
                lines.append(rendered)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                _append_comment_block(lines, comment_block)
                lines.append(f'{node.target.id}: {_annotation_to_source(node.annotation)}')
        elif isinstance(node, ast.FunctionDef):
            decorators = [_decorator_to_source(dec) for dec in node.decorator_list]
            decorators = [item for item in decorators if item]
            _append_comment_block(lines, comment_block)
            for decorator in decorators:
                lines.append(f'@{decorator}')
            signature = _format_arguments(node.args)
            return_annotation = _annotation_to_source(node.returns) if node.returns is not None else 'Any'
            lines.append(f'def {node.name}({signature}) -> {return_annotation}: ...')
        elif isinstance(node, ast.ClassDef):
            bases = []
            for base in node.bases:
                try:
                    bases.append(ast.unparse(base))
                except Exception:
                    bases.append('Any')
            base_expr = f"({', '.join(bases)})" if bases else ''
            _append_comment_block(lines, comment_block)
            lines.append(f'class {node.name}{base_expr}:')
            class_lines: list[str] = []
            class_source_lines = source_lines
            for attr_name, attr_type in _collect_instance_attrs(node).items():
                class_lines.append(f'{attr_name}: {attr_type}')
            for child in node.body:
                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                    class_lines.append(f'{child.target.id}: {_annotation_to_source(child.annotation)}')
                elif isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name):
                            class_lines.append(f'{target.id}: Any')
                elif isinstance(child, ast.FunctionDef):
                    decorators = [_decorator_to_source(dec) for dec in child.decorator_list]
                    decorators = [item for item in decorators if item]
                    for decorator in decorators:
                        class_lines.append(f'@{decorator}')
                    signature = _format_arguments(child.args)
                    return_annotation = _annotation_to_source(child.returns) if child.returns is not None else 'Any'
                    class_lines.append(f'def {child.name}({signature}) -> {return_annotation}: ...')
            if not class_lines:
                class_lines.append('...')
            lines.extend(f'    {line}' for line in class_lines)
        elif isinstance(node, ast.If):
            continue

    lines.append('')
    return '\n'.join(lines)


def _write_workspace_root_stub(root: str) -> bool:
    path = os.path.join(root, 'tools', '__init__.pyi')
    content = '\n'.join([
        'from tools.base.UniqueNameObject import UniqueNameObject',
        'from tools.data.types.DataColumn import DataColumn',
        'from tools.data.types.DataFreq import DataFreq',
        'from tools.data.types.DataTime import DataTime, TimePrecision',
        'from tools.data.views.ProductDataView import ProductDataView',
        'from tools.factors.Factors import Factor',
        'from tools.factors.FactorFamily import FactorFamily',
        '',
        '__all__ = [',
        '    "UniqueNameObject",',
        '    "DataColumn",',
        '    "DataFreq",',
        '    "DataTime",',
        '    "TimePrecision",',
        '    "ProductDataView",',
        '    "Factor",',
        '    "FactorFamily",',
        ']',
        '',
    ])
    return _write_text_if_changed(path, content)


def _write_settings_stub(root: str) -> bool:
    path = os.path.join(root, 'Settings.pyi')
    content = '\n'.join([
        'from __future__ import annotations',
        'from pathlib import Path',
        'from typing import Any',
        '',
        'CACHE_DIR: Path',
        'CACHE_DB_PATH: Path',
        'default_test_start_date: Any',
        'default_test_end_date: Any',
        'default_plot_test_start_date: Any',
        'default_plot_test_end_date: Any',
        'default_day_start_time: Any',
        'default_day_end_time: Any',
        'default_cn_futures_day_start: Any',
        'default_cn_futures_day_end: Any',
        'default_cn_futures_night_start: Any',
        'default_cn_futures_night_end: Any',
        'timezone: Any',
        'factor_info_path: Any',
        'sift_volume_ratio: Any',
        '',
        'def get_all_products(*args, **kwargs): ...',
        'def get_cat_tree(*args, **kwargs): ...',
        '',
    ])
    return _write_text_if_changed(path, content)


def _write_factor_package_stub(root: str) -> bool:
    path = os.path.join(root, 'tools', 'factors', '__init__.pyi')
    content = '\n'.join([
        'from tools.factors.Parameters import FactorNextPeriodReturns, ReturnFreqParam, FactorFreqParam, StartCalcPointParam, ReverseParam',
        'from tools.factors.Factors import Factor',
        'from tools.factors.FactorFamily import FactorFamily',
        'from tools.factors.FactorExpr import (',
        '    FactorExpr,',
        '    ConstExpr,',
        '    ParamRef,',
        '    ColumnRef,',
        '    OperandExpr,',
        '    CompositeExpr,',
        '    ShiftOp,',
        '    CrossSectionalOp,',
        '    WhereOp,',
        '    TermStructureOp,',
        '    signal_align,',
        '    expr_max,',
        '    expr_min,',
        '    OPEN,',
        '    HIGH,',
        '    LOW,',
        '    CLOSE,',
        '    VOLUME,',
        '    TURNOVER,',
        '    OPEN_INTEREST,',
        '    VWAP,',
        '    SETTLE,',
        '    OPEN_RAW,',
        '    HIGH_RAW,',
        '    LOW_RAW,',
        '    CLOSE_RAW,',
        '    SMALL_VAL,',
        ')',
        '',
        '__all__ = [',
        '    "FactorNextPeriodReturns",',
        '    "ReturnFreqParam",',
        '    "FactorFreqParam",',
        '    "StartCalcPointParam",',
        '    "ReverseParam",',
        '    "Factor",',
        '    "FactorFamily",',
        '    "FactorExpr",',
        '    "ConstExpr",',
        '    "ParamRef",',
        '    "ColumnRef",',
        '    "OperandExpr",',
        '    "CompositeExpr",',
        '    "ShiftOp",',
        '    "CrossSectionalOp",',
        '    "WhereOp",',
        '    "TermStructureOp",',
        '    "signal_align",',
        '    "expr_max",',
        '    "expr_min",',
        '    "OPEN",',
        '    "HIGH",',
        '    "LOW",',
        '    "CLOSE",',
        '    "VOLUME",',
        '    "TURNOVER",',
        '    "OPEN_INTEREST",',
        '    "VWAP",',
        '    "SETTLE",',
        '    "OPEN_RAW",',
        '    "HIGH_RAW",',
        '    "LOW_RAW",',
        '    "CLOSE_RAW",',
        '    "SMALL_VAL",',
        ']',
        '',
    ])
    return _write_text_if_changed(path, content)


def _write_parameters_stub(root: str) -> bool:
    path = os.path.join(root, 'tools', 'factors', 'Parameters.pyi')
    content = '\n'.join([
        '# =============================================================================',
        '# tools/factors/Parameters.py',
        '# 因子系统专用参数模块',
        '#',
        '# 定义因子计算中共用的参数单例：',
        '#   ReturnFreqParam       - 收益率计算频率，${RF}，不出现在因子别名中',
        '#   FactorFreqParam       - 因子信号频率，F，出现在因子别名中',
        '#   StartCalcPointParam   - 计算起始点（DataTime），${SCP}，不出现在因子别名中',
        '#   FactorNextPeriodReturns - 下期收益类型枚举（OPEN到OPEN、CLOSE到CLOSE 等）',
        '# =============================================================================',
        '',
        'from enum import Enum',
        'from typing import Optional, Any',
        '',
        'from tools import DataColumn',
        'from tools.parameters import Parameter, DataTimeParam, ValueSpace',
        '',
        'from Settings import default_test_start_date',
        '',
        'def get_reverse_param(alias: Optional[str] = "$Rev", desc: Optional[str] = None) -> Parameter: ...',
        'def get_return_freq_param(alias: Optional[str] = "$RF", desc: Optional[str] = None) -> Parameter: ...',
        'def get_factor_freq_param(alias: Optional[str] = "$F", desc: Optional[str] = None) -> Parameter: ...',
        'def get_StartCalcPointParam(alias: Optional[str] = "$SCP", default_value: Optional[Any] = None, **kwargs) -> DataTimeParam: ...',
        '',
        'ReturnFreqParam: Parameter = ...',
        'FactorFreqParam: Parameter = ...',
        'StartCalcPointParam: DataTimeParam = ...',
        'ReverseParam: Parameter = ...',
        '',
        'class FactorNextPeriodReturns(Enum):',
        '    NEXT_OPEN_TO_OPEN: Any',
        '    NEXT_OPEN_TO_OPEN_ADJUSTED: Any',
        '    THIS_CLOSE_TO_CLOSE: Any',
        '    THIS_CLOSE_TO_CLOSE_ADJUSTED: Any',
        '',
    ])
    return _write_text_if_changed(path, content)


def _write_expr_package_stub(root: str) -> bool:
    path = os.path.join(root, 'tools', 'factors', 'expr', '__init__.pyi')
    content = '\n'.join([
        'from .core import FactorExpr, EvaluateContext',
        '',
        'class PanelTimeline: ...',
        'def build_panel_timeline(*args, **kwargs): ...',
        'def compact_observed(*args, **kwargs): ...',
        'def scatter_observed(*args, **kwargs): ...',
        '',
        'from .operands import OperandExpr',
        'from .leaf import ColumnRef, ParamRef, ConstExpr, _to_expr',
        'from .rolling import RollingExpr, RollingOp, _rolling_argmaxmin, _mask_outside_trunc, _resolve_windows',
        'from .shift import ShiftOp, _is_zero_shift_period, _strip_latex_time_subscript',
        'from .cross_sectional import CrossSectionalOp',
        'from .composite import CompositeExpr, _reduce_biop, expr_max, expr_min',
        'from .conditional import WhereOp',
        'from .term_structure import TermStructureOp, term_spread, term_ratio, term_slope',
        'from .signal_align import SignalAlign, signal_align',
        'from .visual_groups import (',
        '    VISUAL_OPERATOR_GROUPS,',
        '    VISUAL_COMPOSITE_KEY,',
        '    VISUAL_OPERATOR_CATEGORY,',
        '    get_visual_operator_groups,',
        '    get_visual_composite_key,',
        '    get_visual_operator_category,',
        ')',
        '',
        'from tools.data.types.DataColumn import DataColumn',
        '',
        'OPEN = ColumnRef(DataColumn.OPEN_ADJUSTED)',
        'HIGH = ColumnRef(DataColumn.HIGH_ADJUSTED)',
        'LOW = ColumnRef(DataColumn.LOW_ADJUSTED)',
        'CLOSE = ColumnRef(DataColumn.CLOSE_ADJUSTED)',
        'VOLUME = ColumnRef(DataColumn.VOLUME)',
        'TURNOVER = ColumnRef(DataColumn.TURNOVER)',
        'OPEN_INTEREST = ColumnRef(DataColumn.OPEN_INTEREST)',
        'VWAP = ColumnRef(DataColumn.VWAP)',
        'SETTLE = ColumnRef(DataColumn.SETTLEMENT_PRICE)',
        'OPEN_RAW = ColumnRef(DataColumn.OPEN)',
        'HIGH_RAW = ColumnRef(DataColumn.HIGH)',
        'LOW_RAW = ColumnRef(DataColumn.LOW)',
        'CLOSE_RAW = ColumnRef(DataColumn.CLOSE)',
        'SMALL_VAL = ConstExpr(1e-10)',
        '',
        '__all__ = [',
        '    "FactorExpr", "EvaluateContext", "OperandExpr", "ColumnRef", "ParamRef", "ConstExpr", "_to_expr",',
        '    "RollingExpr", "RollingOp", "_rolling_argmaxmin", "_mask_outside_trunc", "_resolve_windows",',
        '    "ShiftOp", "_is_zero_shift_period", "_strip_latex_time_subscript",',
        '    "CrossSectionalOp", "CompositeExpr", "_reduce_biop", "expr_max", "expr_min",',
        '    "WhereOp", "TermStructureOp", "term_spread", "term_ratio", "term_slope",',
        '    "SignalAlign", "signal_align",',
        '    "VISUAL_OPERATOR_GROUPS", "VISUAL_COMPOSITE_KEY", "VISUAL_OPERATOR_CATEGORY",',
        '    "get_visual_operator_groups", "get_visual_composite_key", "get_visual_operator_category",',
        '    "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME", "TURNOVER", "OPEN_INTEREST", "VWAP", "SETTLE",',
        '    "OPEN_RAW", "HIGH_RAW", "LOW_RAW", "CLOSE_RAW", "SMALL_VAL",',
        ']',
        '',
    ])
    return _write_text_if_changed(path, content)


def _merge_json_object(path: str, updates: dict[str, Any]) -> bool:
    payload: dict[str, Any] = {}
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as file:
                loaded = json.load(file)
            if isinstance(loaded, dict):
                payload = loaded
        except Exception:
            payload = {}
    changed = False
    for key, value in updates.items():
        if payload.get(key) != value:
            payload[key] = value
            changed = True
    if not os.path.exists(path) or changed:
        return _write_json(path, payload)
    return False


def _remove_missing_files(directory: str, expected_names: set[str]) -> list[str]:
    removed: list[str] = []
    if not os.path.isdir(directory):
        return removed
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith('.py'):
            continue
        if filename in expected_names:
            continue
        path = os.path.join(directory, filename)
        if os.path.isfile(path):
            os.remove(path)
            removed.append(path)
    return removed


def _sync_tools_index(root: str) -> bool:
    tools_dir = os.path.join(os.getcwd(), 'tools')
    tool_files = scan_tool_files(tools_dir, include_symbols=True)
    payload = {
        'workspace_root': root,
        'tools_dir': tools_dir,
        'generated_at': time.time(),
        'files': tool_files,
    }
    return _write_json(os.path.join(root, 'tools_index.json'), payload)


def _sync_tools_sdk(root: str) -> bool:
    source_root = _source_tools_dir()
    workspace_root = _workspace_tools_dir(root)
    touched = False
    expected_files: set[str] = set()

    for current_root, dirs, filenames in os.walk(source_root):
        dirs[:] = [d for d in sorted(dirs) if not d.startswith('__pycache__') and not d.startswith('.')]
        rel_dir = os.path.relpath(current_root, source_root)
        for filename in sorted(filenames):
            if not filename.endswith('.py'):
                continue
            source_path = os.path.join(current_root, filename)
            rel_path = filename if rel_dir == '.' else os.path.join(rel_dir, filename)
            if rel_path not in _TOOLS_STUB_MODULES:
                continue
            dest_rel_path = rel_path[:-3] + '.pyi'
            expected_files.add(dest_rel_path)
            dest_path = os.path.join(workspace_root, dest_rel_path)
            with open(source_path, 'r', encoding='utf-8') as file:
                source_code = file.read()
            stub_code = _render_stub_module(source_code, rel_path)
            if _write_text_if_changed(dest_path, stub_code):
                touched = True

    for current_root, dirs, filenames in os.walk(workspace_root):
        dirs[:] = [d for d in sorted(dirs) if not d.startswith('__pycache__') and not d.startswith('.')]
        rel_dir = os.path.relpath(current_root, workspace_root)
        for filename in sorted(filenames):
            if not (filename.endswith('.pyi') or filename.endswith('.py')):
                continue
            if filename.endswith('.pyi'):
                rel_path = filename if rel_dir == '.' else os.path.join(rel_dir, filename)
            else:
                rel_path = (filename[:-3] + '.pyi') if rel_dir == '.' else os.path.join(rel_dir, filename[:-3] + '.pyi')
            if rel_path not in expected_files:
                os.remove(os.path.join(current_root, filename))
                touched = True

    # 专用白名单 stub 放在最后写，避免被通用 AST 渲染覆盖。
    touched |= _write_workspace_root_stub(root)
    touched |= _write_settings_stub(root)
    touched |= _write_parameters_stub(root)
    touched |= _write_factor_package_stub(root)
    touched |= _write_expr_package_stub(root)
    return touched


def _sync_vscode_settings(root: str) -> bool:
    settings_path = os.path.join(root, '.vscode', 'settings.json')
    extra_paths = [
        '${workspaceFolder}',
    ]
    updates = {
        'python.analysis.extraPaths': extra_paths,
        'python.analysis.autoSearchPaths': True,
    }
    return _merge_json_object(settings_path, updates)


def _load_workspace_config(username: str) -> dict[str, Any]:
    settings = load_factor_source_workspace_settings(username) or {}
    return {
        'git_enabled': bool(settings.get('git_enabled')),
        'git_repo_root': str(settings.get('git_repo_root') or ''),
        'auto_sync_branch': str(settings.get('auto_sync_branch') or ''),
        'force_sync_branch': str(settings.get('force_sync_branch') or ''),
    }


def get_factor_workspace_git_state(username: str) -> dict[str, Any]:
    root = _workspace_root(username)
    settings = load_factor_source_workspace_settings(username) or {}
    repo_root = str(settings.get('git_repo_root') or '')
    branches = _git_branch_names(root) if os.path.isdir(root) else []
    return {
        'workspace_root': root,
        'git_enabled': bool(settings.get('git_enabled')),
        'git_repo_root': repo_root,
        'git_current_branch': _git_current_branch(root) or '',
        'git_auto_sync_branch': str(settings.get('auto_sync_branch') or ''),
        'git_force_sync_branch': str(settings.get('force_sync_branch') or ''),
        'git_branches': branches,
    }


def sync_database_to_workspace(username: str, branch_mode: str = 'auto') -> dict[str, Any]:
    root = _workspace_root(username)
    _ensure_workspace_layout(root)
    git_info = _ensure_git_workspace(root, username)
    selected_branch = _apply_workspace_git_branch(root, username, branch_mode)

    custom_count = 0
    public_count = 0
    touched_files = []
    expected_custom_files: set[str] = set()
    expected_public_files: set[str] = set()

    for record in list_factor_sources('custom'):
        owner_username = str(record.get('owner_username') or '')
        factor_id = str(record.get('factor_id') or '')
        source_code = str(record.get('source_code') or '')
        if not owner_username or not factor_id or not source_code:
            continue
        if owner_username != username:
            continue
        expected_custom_files.add(f'{factor_id}.py')
        local_path = _storage().factor_path(username, factor_id)
        if _write_text_if_changed(local_path, source_code):
            touched_files.append(local_path)
        custom_count += 1

    for record in list_factor_sources('public'):
        factor_id = str(record.get('factor_id') or '')
        source_code = str(record.get('source_code') or '')
        if not factor_id or not source_code:
            continue
        expected_public_files.add(f'{factor_id}.py')
        local_path = os.path.join(_workspace_public_dir(root), f'{factor_id}.py')
        if _write_text_if_changed(local_path, source_code):
            touched_files.append(local_path)
        public_count += 1

    removed_files = []
    removed_files.extend(_remove_missing_files(_workspace_custom_dir(root), expected_custom_files))
    removed_files.extend(_remove_missing_files(_workspace_public_dir(root), expected_public_files))

    tools_index_changed = _sync_tools_index(root)
    tools_sdk_changed = _sync_tools_sdk(root)
    vscode_settings_changed = _sync_vscode_settings(root)

    manifest = {
        'workspace_root': root,
        'username': username,
        'custom_factor_dir': _storage().custom_factor_dir(username),
        'public_factor_dir': _workspace_public_dir(root),
        'git': git_info,
        'git_selected_branch': selected_branch,
        'custom_factor_count': custom_count,
        'public_factor_count': public_count,
        'touched_files': touched_files,
        'removed_files': removed_files,
    }
    manifest_changed = _write_json(os.path.join(root, '.factor_workspace', 'manifest.json'), manifest)

    return {
        'workspace_root': root,
        'custom_factor_count': custom_count,
        'public_factor_count': public_count,
        'git': git_info,
        'git_selected_branch': selected_branch,
        'touched_files': touched_files,
        'removed_files': removed_files,
        'tools_index_changed': tools_index_changed,
        'tools_sdk_changed': tools_sdk_changed,
        'vscode_settings_changed': vscode_settings_changed,
        'manifest_changed': manifest_changed,
    }


def build_factor_workspace(username: str) -> dict[str, Any]:
    return sync_database_to_workspace(username, branch_mode='force')


def sync_factor_workspace(username: str, branch_mode: str = 'force') -> dict[str, Any]:
    return sync_database_to_workspace(username, branch_mode=branch_mode)


def sync_workspace_to_database(username: str, branch_mode: str = 'auto') -> dict[str, Any]:
    root = _workspace_root(username)
    _ensure_workspace_layout(root)
    _ensure_git_workspace(root, username)
    selected_branch = _apply_workspace_git_branch(root, username, branch_mode)

    custom_dir = _storage().custom_factor_dir(username)
    updated_custom = 0
    updated_public = 0

    if os.path.isdir(custom_dir):
        for filename in sorted(os.listdir(custom_dir)):
            if not filename.endswith('.py'):
                continue
            factor_id = filename[:-3]
            source = _storage().load_factor_source(username, factor_id)
            file_path = os.path.join(custom_dir, filename)
            with open(file_path, 'r', encoding='utf-8') as file:
                source_code = file.read()
            if source != source_code:
                _storage().save_factor_source(username, factor_id, source_code)
                updated_custom += 1

    public_dir = _workspace_public_dir(root)
    if os.path.isdir(public_dir):
        for filename in sorted(os.listdir(public_dir)):
            if not filename.endswith('.py'):
                continue
            factor_id = filename[:-3]
            file_path = os.path.join(public_dir, filename)
            with open(file_path, 'r', encoding='utf-8') as file:
                source_code = file.read()
            if _storage().load_public_factor_source(factor_id) != source_code:
                _storage().save_public_factor_source(factor_id, source_code)
                updated_public += 1

    return {
        'workspace_root': root,
        'git_selected_branch': selected_branch,
        'updated_custom_count': updated_custom,
        'updated_public_count': updated_public,
    }


def push_factor_workspace(username: str, allow_public_write: bool = False, branch_mode: str = 'auto') -> dict[str, Any]:
    root = _workspace_root(username)
    _ensure_workspace_layout(root)
    _ensure_git_workspace(root, username)
    selected_branch = _apply_workspace_git_branch(root, username, branch_mode)

    public_dir = _workspace_public_dir(root)
    changed_public_files: list[str] = []
    if os.path.isdir(public_dir):
        for filename in sorted(os.listdir(public_dir)):
            if not filename.endswith('.py'):
                continue
            factor_id = filename[:-3]
            file_path = os.path.join(public_dir, filename)
            with open(file_path, 'r', encoding='utf-8') as file:
                source_code = file.read()
            if _storage().load_public_factor_source(factor_id) != source_code:
                changed_public_files.append(file_path)

    if changed_public_files and not allow_public_write:
        rel = [os.path.relpath(path, root) for path in changed_public_files]
        raise PermissionError(f'只有超级管理员可以同步公共因子到数据库：{rel}')

    result = sync_workspace_to_database(username, branch_mode=branch_mode)
    result['git_selected_branch'] = selected_branch or result.get('git_selected_branch', '')
    return result
