# =============================================================================
# server/services/data_dictionary.py
# 数据字典扫描器
#
# 自动扫描项目中的字段定义并生成结构化元数据，用于：
#   1. 前端数据字典页面渲染
#   2. SOE 合规审计导出
#   3. 与代码保持自动同步，避免文档过期
#
# 扫描范围：
#   - DataColumn 枚举（数据列字段）
#   - FactorFamily 子类（因子元信息）
#   - Settings 配置项
#   - 全局常量/参数
# =============================================================================
from __future__ import annotations

import ast
import importlib
import importlib.util  # noqa: F401 — pyright needs this to recognise importlib.util
import inspect
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════════════

@dataclass
class DataColumnEntry:
    """数据列字段字典条目"""
    name: str           # 枚举成员名，如 'OPEN'
    code: str           # 存储代号，如 'O'
    description: str    # 中文说明，如 '开盘价'


@dataclass
class FactorEntry:
    """因子字典条目"""
    name: str               # 类名，如 'MmRet'
    desc: str               # 简短中文名，如 '收益率动量'
    description: str        # 详细说明（Markdown）
    math_expr: str          # LaTeX 公式
    category: str           # 分组前缀，如 'Mm'
    source_file: str        # 源文件，如 'Factors/MmRet.py'
    params: List[ParamEntry] = field(default_factory=list)


@dataclass
class ParamEntry:
    """参数字典条目"""
    alias: str          # 参数别名，如 '$F'
    type: str           # 参数类型，如 'WindowParam'
    default_value: str  # 默认值
    description: str    # 中文说明


@dataclass
class SettingEntry:
    """全局配置字典条目"""
    name: str           # 变量名
    value: str          # 当前值
    description: str    # 中文说明


@dataclass
class DataSourceEntry:
    """数据源字典条目"""
    alias: str          # 别名，如 'local_cn_futures'
    freq: str           # 数据频率，如 'DAY1'
    timezone: str       # 时区
    columns_count: int  # 列映射数量
    columns_list: str   # 列映射摘要


@dataclass
class ParamTypeEntry:
    """参数类型字典条目"""
    name: str           # 类型名，如 'WindowParam'
    alias: str          # 参数别名格式，如 '$W'
    description: str    # 类型说明
    default_example: str  # 默认值示例


@dataclass
class DataDictionary:
    """完整数据字典"""
    generated_at: str = ""
    data_columns: List[DataColumnEntry] = field(default_factory=list)
    frequency_types: List[dict] = field(default_factory=list)     # DataFreq 类型清单
    data_sources: List[DataSourceEntry] = field(default_factory=list)
    param_types: List[ParamTypeEntry] = field(default_factory=list)
    factors: List[FactorEntry] = field(default_factory=list)
    settings: List[SettingEntry] = field(default_factory=list)
    factor_categories: Dict[str, str] = field(default_factory=dict)  # 分组前缀 → 分组中文名


# ═══════════════════════════════════════════════════════════════════
# 扫描器
# ═══════════════════════════════════════════════════════════════════

def _extract_docstring_description(docstring: str | None) -> str:
    """从 docstring 中提取第一句有意义的中文描述。"""
    if not docstring:
        return ""
    lines = docstring.strip().split('\n')
    for line in lines:
        line = line.strip()
        # 跳过空行和标题标记
        if not line or line.startswith('#') or line.startswith('=') or line.startswith('-'):
            continue
        # 取前 200 字符作为简短描述
        return line[:200]
    return ""


def scan_data_columns() -> List[DataColumnEntry]:
    """扫描 DataColumn 枚举，提取所有数据列字段。"""
    from tools.data.DataColumn import DataColumn
    entries = []
    for member in DataColumn:
        # 从枚举成员的 docstring 或源码推测中文描述
        entries.append(DataColumnEntry(
            name=member.name,
            code=member.value,
            description="",  # 下文从源码注释提取
        ))
    return entries


def _extract_enum_comments(filepath: str, class_name: str) -> Dict[str, str]:
    """从 Python 源码中提取枚举成员的尾注注释。"""
    comments: Dict[str, str] = {}
    try:
        with open(filepath, 'r') as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                # 取尾注（# 后面的内容）
                                if item.end_lineno:
                                    last_line = source.split('\n')[item.end_lineno - 1]
                                else:
                                    last_line = source.split('\n')[item.lineno - 1]
                                comment_match = re.search(r'#\s*(.+)$', last_line)
                                if comment_match:
                                    comments[target.id] = comment_match.group(1).strip()
    except Exception:
        pass
    return comments


def scan_data_columns_with_comments() -> List[DataColumnEntry]:
    """扫描 DataColumn 并补全中文注释。"""
    entries = scan_data_columns()
    filepath = os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'data', 'DataColumn.py')
    filepath = os.path.normpath(filepath)
    comments = _extract_enum_comments(filepath, 'DataColumn')
    for entry in entries:
        if not entry.description:
            entry.description = comments.get(entry.name, '')
    return entries


def scan_factors() -> List[FactorEntry]:
    """扫描所有 FactorFamily 子类，提取因子元信息。"""
    from tools.factors.FactorFamily import FactorFamily
    factors_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'Factors')
    factors_dir = os.path.normpath(factors_dir)

    # 因子分组中文名映射
    category_names = {
        'Mm': '动量因子',
        'Oi': '持仓因子',
        'Vl': '波动率因子',
        'Vp': '量价因子',
    }

    entries: List[FactorEntry] = []
    try:
        filenames = sorted(f for f in os.listdir(factors_dir) if f.endswith('.py') and f[0].isupper())

        for filename in filenames:
            factor_name = os.path.splitext(filename)[0]
            module_name = factor_name
            try:
                spec = importlib.util.spec_from_file_location(
                    module_name,
                    os.path.join(factors_dir, filename)
                )
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                for attr_name in dir(module):
                    obj = getattr(module, attr_name)
                    if (isinstance(obj, type)
                            and issubclass(obj, FactorFamily)
                            and obj is not FactorFamily):
                        entry = FactorEntry(
                            name=obj.__name__,
                            desc=getattr(obj, 'desc', ''),
                            description=getattr(obj, 'description', ''),
                            math_expr=getattr(obj, 'math_expr', ''),
                            category=_factor_group_key(obj.__name__),
                            source_file=f'Factors/{filename}',
                        )
                        # 提取参数信息
                        entry.params = _extract_factor_params(obj)
                        entries.append(entry)
                        break  # 每个文件只取第一个 FactorFamily 子类
            except Exception as e:
                print(f"[data_dictionary] 跳过 {filename}: {e}")
    except FileNotFoundError:
        pass

    return entries


def _factor_group_key(name: str) -> str:
    """从因子名提取分组前缀（如 MmRet → Mm）。"""
    group = ""
    upper_count = 0
    for char in name:
        if char.isupper():
            upper_count += 1
            group += char
            if upper_count == 2:
                break
        elif upper_count == 1:
            group += char
    return group if group else name


def _extract_factor_params(cls: type) -> List[ParamEntry]:
    """从 FactorFamily 类提取参数列表。"""
    entries = []
    try:
        params = getattr(cls, 'params', [])
        for p in params:
            entries.append(ParamEntry(
                alias=getattr(p, 'alias', str(p)),
                type=type(p).__name__,
                default_value=str(getattr(p, 'default_value', '')),
                description=getattr(p, 'desc', '') or '',
            ))
    except Exception:
        pass
    return entries


def scan_settings() -> List[SettingEntry]:
    """扫描 Settings.py 中的顶层配置变量。"""
    import Settings
    entries = []
    filepath = os.path.join(os.path.dirname(__file__), '..', '..', 'Settings.py')
    filepath = os.path.normpath(filepath)

    # 从源码提取注释
    var_comments: Dict[str, str] = {}
    try:
        with open(filepath, 'r') as f:
            lines = f.readlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            # 捕获前一行的 # 注释
            if i > 0 and lines[i-1].strip().startswith('#'):
                comment = lines[i-1].strip().lstrip('#').strip()
                # 找到下一个赋值语句
                match = re.match(r'^(\w+)\s*[:=]', line)
                if match:
                    var_comments[match.group(1)] = comment
            i += 1
    except Exception:
        pass

    # 遍历 Settings 模块的公有属性
    for name in dir(Settings):
        if name.startswith('_'):
            continue
        value = getattr(Settings, name)
        if callable(value) or inspect.ismodule(value) or inspect.isclass(value):
            continue
        entries.append(SettingEntry(
            name=name,
            value=str(value)[:200],
            description=var_comments.get(name, ''),
        ))

    return entries


def scan_data_sources() -> List[DataSourceEntry]:
    """扫描当前已注册的 DataSource 实例，不负责触发加载。"""
    from tools.data.DataSource import DataSourceMeta
    entries = []
    try:
        # DataSourceMeta._data_sources 是强引用字典
        for alias, source in sorted(DataSourceMeta._data_sources.items()):
            cols_list = []
            data_cols = getattr(source, 'data_cols_mapping', None) or {}
            for csv_col, dc in data_cols.items():
                dc_name = dc.name if hasattr(dc, 'name') else str(dc)
                cols_list.append(f"{csv_col}→{dc_name}")
            entries.append(DataSourceEntry(
                alias=alias,
                freq=str(getattr(source, 'freq', '?')),
                timezone=str(getattr(source, 'timezone', 'None')),
                columns_count=len(cols_list),
                columns_list=', '.join(cols_list[:15]) + ('...' if len(cols_list) > 15 else ''),
            ))
    except Exception as e:
        print(f"[data_dictionary] 扫描 DataSource 失败: {e}")
    return entries


def scan_param_types() -> List[ParamTypeEntry]:
    """扫描参数系统类型。"""
    param_types_info = [
        ('WindowParam', '$W', '窗口参数：正整数或正 Timedelta，如 10 表示回看10根K线', '1'),
        ('DataColumnParam', '$P', '数据列参数：选择 OHLC/V/OI 等价格/量列', 'CLOSE'),
        ('DateOrTimeParam', '$Date/$Time', '日期/时间参数：支持日期字符串或 time 对象', "'2024-01-01'"),
        ('FinRangeParam', '—', '有限枚举参数：从预定义列表中选取一个值', '第一个选项'),
        ('TypeParam', '—', '类型约束参数：限制值为特定 Python 类型', '—'),
        ('TimeDeltaParam', '—', '时间增量参数：支持正/负/非负等约束的 pd.Timedelta', '—'),
        ('FactorParam', '—', '因子参数：引用另一个 FactorFamily 实例', '—'),
    ]
    return [
        ParamTypeEntry(name=n, alias=a, description=d, default_example=de)
        for n, a, d, de in param_types_info
    ]


def scan_frequency_types() -> List[dict]:
    """扫描已创建的 DataFreq 实例。通过访问常见频率触发懒加载。"""
    from tools.data.DataFreq import DataFreq
    # 触发常见频率的懒加载实例化，并用列表保持引用防止 WeakValueDictionary GC
    _freqs = []
    for attr in ('MIN1', 'MIN5', 'MIN15', 'MIN30', 'MIN60', 'DAY1'):
        try:
            _freqs.append(getattr(DataFreq, attr))
        except Exception:
            pass
    freqs = []
    try:
        # DataFreq._instances 的 key 是 (name, structural_key) 元组
        for f in DataFreq._instances.values():
            freqs.append({
                'name': f.name,
                'value': str(f.value),
                'alias': f.alias,
            })
    except Exception:
        pass
    return sorted(freqs, key=lambda x: x['name'])


def build_data_dictionary() -> DataDictionary:
    """构建完整数据字典。"""
    from datetime import datetime
    try:
        from sources import load_all_sources

        load_all_sources()
    except Exception:
        pass
    return DataDictionary(
        generated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        data_columns=scan_data_columns_with_comments(),
        frequency_types=scan_frequency_types(),
        data_sources=scan_data_sources(),
        param_types=scan_param_types(),
        factors=scan_factors(),
        settings=scan_settings(),
        factor_categories={
            'Mm': '动量因子',
            'Oi': '持仓因子',
            'Vl': '波动率因子',
            'Vp': '量价因子',
        },
    )


# ═══════════════════════════════════════════════════════════════════
# 导出
# ═══════════════════════════════════════════════════════════════════

def data_dictionary_to_dict(dd: DataDictionary) -> dict:
    """将 DataDictionary 转为可 JSON 序列化的 dict。"""
    return {
        'generated_at': dd.generated_at,
        'data_columns': [
            {'name': e.name, 'code': e.code, 'description': e.description}
            for e in dd.data_columns
        ],
        'frequency_types': dd.frequency_types,
        'data_sources': [
            {
                'alias': e.alias,
                'freq': e.freq,
                'timezone': e.timezone,
                'columns_count': e.columns_count,
                'columns_list': e.columns_list,
            }
            for e in dd.data_sources
        ],
        'param_types': [
            {'name': e.name, 'alias': e.alias, 'description': e.description, 'default_example': e.default_example}
            for e in dd.param_types
        ],
        'factors': [
            {
                'name': e.name,
                'desc': e.desc,
                'description': e.description,
                'math_expr': e.math_expr,
                'category': e.category,
                'source_file': e.source_file,
                'params': [
                    {'alias': p.alias, 'type': p.type, 'default_value': p.default_value, 'description': p.description}
                    for p in e.params
                ],
            }
            for e in dd.factors
        ],
        'settings': [
            {'name': e.name, 'value': e.value, 'description': e.description}
            for e in dd.settings
        ],
        'factor_categories': dd.factor_categories,
    }
