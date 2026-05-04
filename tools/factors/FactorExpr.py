# =============================================================================
# tools/factors/FactorExpr.py
# 因子表达式系统
#
# 核心思想：因子 = 表达式树，通过运算符组合基本列引用和算子，
# 自动构建依赖关系图，运行时按依赖拓扑顺行求值。
#
# 设计架构（三层）：
#
#   Layer 1 — 叶子节点 (FactorTerm)
#     引用基础数据列：OPEN, HIGH, LOW, CLOSE, VOLUME, ...
#     每个品种有自己的一条时序，组合后形成横截面 DataFrame
#
#   Layer 2 — 算子节点 (FactorOp)
#     时序算子（按品种独立计算）：MA, STD, REF, DELTA, LOG, ...
#     横截面算子（逐时间点计算）：CS_ZSCORE, CS_RANK, CS_WEIGHTED, ...
#
#   Layer 3 — 表达式组合 (FactorExpr)
#     算术运算：expr1 + expr2, expr1 - expr2, expr1 * expr2, expr1 / expr2
#     比较运算：expr1 > expr2, expr1 == expr2
#     逻辑运算：expr1 & expr2, expr1 | expr2
#     聚合运算：max(expr1, expr2, ...), min(expr1, expr2, ...)
#
# 表达式求值：
#   1. 构建依赖 DAG（每个节点记录其上游依赖）
#   2. 拓扑排序确定求值顺序
#   3. 每个节点从 product.{freq} 获取原始数据，计算自身结果并缓存
#   4. 最终返回 "products × time" 的 DataFrame
#
# =============================================================================
from __future__ import annotations

import pandas as pd
import numpy as np
from functools import partial
from typing import (
    TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union, cast
)
from weakref import WeakValueDictionary

from tools.base.UniqueObject import UniqueObject
from tools.data.DataColumn import DataColumn
from tools.data.DataFreq import DataFreq

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.factors.FactorFamily import FactorFamily
    from tools.factors.Factor import Factor
    from tools.data.DataSource import DataSource
    from tools.data.DataMeta import DataMeta
    from tools.parameters.Parameter import Parameter


# ═════════════════════════════════════════════════════════════════════════════
# Layer 1: 因子表达式基类
# ═════════════════════════════════════════════════════════════════════════════

class FactorExpr:
    """
    因子表达式抽象基类。

    所有叶子节点、算子节点、复合表达式都继承此类。
    核心能力：
      - 运算符重载（+, -, *, /, >, <, ==, &, |）
      - 依赖追踪（.dependencies 返回上游节点集合）
      - 求值接口（.evaluate(data, source=...) → DataFrame）
      - LaTeX 表达式生成（.to_latex() → str）

    数据源：
      evaluate() 接受 source: DataSource 参数。若未指定，自动为每个品种
      选择包含所需列的第一个可用数据源；若指定了 source，校验是否兼容后使用。
    """

    __array_priority__ = 1000

    # ── 中间因子标记 ──

    _is_intermediate: bool = False
    _intermediate_name: 'str | None' = None

    def as_intermediate(self, name: 'str | None' = None) -> 'FactorExpr':
        """标记此表达式节点为中间因子，evaluate 时自动创建 FactorData。

        name: 可选名称，用于后续查询（如 'FE', 'RE'）。
              None 表示匿名中间因子（仅创建 FactorData 不做命名映射）。
        """
        self._is_intermediate = True
        self._intermediate_name = name
        return self

    # ── 可哈希（用于 set/dict 中的依赖追踪和缓存） ──

    def __hash__(self) -> int:
        return id(self)

    # ── 结构等价（用于 FactorData 去重 key） ──

    _SYMMETRIC_OPS = frozenset({
        'add', 'mul', 'and', 'or', 'max', 'min', 'eq', 'ne',
        'cs_spearman', 'cs_corr', 'cs_cov',
    })

    def _structural_hash(self) -> int:
        """
        递归计算表达式树的结构 hash。

        对于对称二元运算，operand 顺序无关（先 sort operands 的 hash）。
        对于非对称运算，按原始顺序计算。
        """
        return hash(self._structural_key())

    def _structural_key(self) -> tuple:
        """
        返回表达式树的标准化元组表示，用于结构等价判断和 hash。

        格式：(type_tag, ...type_specific...)
        """
        raise NotImplementedError(
            f"{type(self).__name__} 未实现 _structural_key()")

    def _structural_eq(self, other: 'FactorExpr') -> bool:
        """基于结构的表达式等价判断。"""
        if type(self) is not type(other):
            return False
        return self._structural_key() == other._structural_key()

    # ── 子类必须实现的接口 ──

    def resolve(self, *args, **kwargs) -> 'FactorExpr':
        """将 ParamRef → 对应的 ConstExpr 或 ColumnRef（取决于参数值类型）。"""
        return self

    def evaluate(self, *args, **kwargs) -> pd.DataFrame:
        """求值：对给定品种集合和数据频率，计算因子值。"""
        raise NotImplementedError

    @property
    def op_name(self) -> str:
        """表达式操作名，用于生成别名和 LaTeX。"""
        raise NotImplementedError

    def to_latex(self) -> str:
        """生成 LaTeX 数学表达式。"""
        raise NotImplementedError

    def _get_alias(self) -> str:
        """生成唯一别名，用于 Factor 注册。"""
        raise NotImplementedError

    @property
    def dependencies(self) -> Set['FactorExpr']:
        """返回此节点依赖的上游表达式集合（不含自身）。"""
        return set()

    @property
    def param_deps(self) -> Set['Parameter']:
        """返回此节点依赖的参数集合。"""
        return set()

    def _collect_params_ordered(self, seen: Set['Parameter'], result: List['Parameter']):
        """深度优先遍历收集参数，结果按首次出现顺序存入 result。"""
        pass

    @property
    def ordered_param_deps(self) -> List['Parameter']:
        seen: Set['Parameter'] = set()
        result: List['Parameter'] = []
        self._collect_params_ordered(seen, result)
        return result
    
    def get_ref_types(self, typ: type) -> Set[Any]:
        """收集表达式树中的所有指定类型的引用节点。"""
        result: Set[Any] = set()
        seen: set[tuple] = set()  # 用 structural_key 去重
        stack: list[FactorExpr] = [self]

        while stack:
            node = stack.pop()
            sk = node._structural_key()
            if sk in seen:
                continue
            seen.add(sk)
            if isinstance(node, typ):
                result.add(node)
            for op in getattr(node, '_operands', []):
                stack.append(op)

        return result

    @property
    def column_refs(self) -> Set['ColumnRef']:
        """收集表达式树中的所有 ColumnRef 叶子节点。"""
        return self.get_ref_types(ColumnRef)

    @property
    def const_refs(self) -> Set['ConstExpr']:
        """收集表达式树中的所有 ConstExpr 叶子节点"""
        return self.get_ref_types(ConstExpr)

    # ── 运算符重载：自动构建 CompositeExpr ──

    def __add__(self, other: Any) -> 'CompositeExpr':
        return CompositeExpr('add', self, _to_expr(other))

    def __radd__(self, other: Any) -> 'CompositeExpr':
        return CompositeExpr('add', _to_expr(other), self)

    def __sub__(self, other: Any) -> 'CompositeExpr':
        return CompositeExpr('sub', self, _to_expr(other))

    def __rsub__(self, other: Any) -> 'CompositeExpr':
        return CompositeExpr('sub', _to_expr(other), self)

    def __mul__(self, other: Any) -> 'CompositeExpr':
        return CompositeExpr('mul', self, _to_expr(other))

    def __rmul__(self, other: Any) -> 'CompositeExpr':
        return CompositeExpr('mul', _to_expr(other), self)

    def __truediv__(self, other: Any) -> 'CompositeExpr':
        return CompositeExpr('div', self, _to_expr(other))

    def __rtruediv__(self, other: Any) -> 'CompositeExpr':
        return CompositeExpr('div', _to_expr(other), self)

    def __neg__(self) -> 'CompositeExpr':
        return CompositeExpr('neg', self)

    def __pos__(self) -> 'FactorExpr':
        return self

    def __abs__(self) -> 'CompositeExpr':
        return CompositeExpr('abs', self)

    def __gt__(self, other: Any) -> 'CompositeExpr':
        return CompositeExpr('gt', self, _to_expr(other))

    def __lt__(self, other: Any) -> 'CompositeExpr':
        return CompositeExpr('lt', self, _to_expr(other))

    def __ge__(self, other: Any) -> 'CompositeExpr':
        return CompositeExpr('ge', self, _to_expr(other))

    def __le__(self, other: Any) -> 'CompositeExpr':
        return CompositeExpr('le', self, _to_expr(other))

    def __eq__(self, other: Any) -> 'CompositeExpr':  # type: ignore[override]
        return CompositeExpr('eq', self, _to_expr(other))

    def __ne__(self, other: Any) -> 'CompositeExpr':  # type: ignore[override]
        return CompositeExpr('ne', self, _to_expr(other))

    def __and__(self, other: Any) -> 'CompositeExpr':
        return CompositeExpr('and', self, _to_expr(other))

    def __or__(self, other: Any) -> 'CompositeExpr':
        return CompositeExpr('or', self, _to_expr(other))

    def __invert__(self) -> 'CompositeExpr':
        return CompositeExpr('not', self)

    def __pow__(self, other: Any) -> 'CompositeExpr':
        """幂运算：self ** other。"""
        return CompositeExpr('pow', self, _to_expr(other))

    def max(self, other: Any) -> 'CompositeExpr':
        """逐元素最大值：fmax(self, other)。"""
        return CompositeExpr('max', self, _to_expr(other))

    def min(self, other: Any) -> 'CompositeExpr':
        """逐元素最小值：fmin(self, other)。"""
        return CompositeExpr('min', self, _to_expr(other))

    # ── 便利方法：时序算子 ──

    def ma(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期移动平均（简单平均）。"""
        return RollingOp('ma', _to_expr(window), self)

    def std(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期移动标准差。"""
        return RollingOp('std', _to_expr(window), self)

    def var(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期移动方差。"""
        return RollingOp('var', _to_expr(window), self)

    def rolling_min(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期滚动最小值。"""
        return RollingOp('min', _to_expr(window), self)

    def rolling_max(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期滚动最大值。"""
        return RollingOp('max', _to_expr(window), self)

    def rolling_sum(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期滚动求和。"""
        return RollingOp('sum', _to_expr(window), self)

    def ema(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期指数移动平均（EMA, span=window）。"""
        return RollingOp('ema', _to_expr(window), self)

    def corr(self, other: 'FactorExpr', window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期滚动相关系数：self 与 other 的 rolling correlation。"""
        return RollingOp('corr', _to_expr(window), self, other)

    def skew(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期滚动偏度。"""
        return RollingOp('skew', _to_expr(window), self)

    def argmax(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期内最大值出现位置（0=最早, 1=最新），归一化到 [0,1]。"""
        return RollingOp('argmax', _to_expr(window), self)

    def argmin(self, window: Union[int, str, pd.Timedelta]) -> 'RollingOp':
        """N 期内最小值出现位置（0=最早, 1=最新），归一化到 [0,1]。"""
        return RollingOp('argmin', _to_expr(window), self)

    def shift(self, periods: Union[int, str, pd.Timedelta, 'Parameter'] = 1) -> 'ShiftOp':
        """前 N 期值：x.shift(1) 即昨天值。"""
        return ShiftOp('shift', periods, self)

    def delta(self, period: Union[int, str, pd.Timedelta, 'Parameter'] = 1) -> 'CompositeExpr':
        """N 期变化量：self - self.shift(N)。"""
        return self - self.shift(period)

    def log(self) -> 'UnaryOp':
        """自然对数。"""
        return UnaryOp('log', self)

    def sign(self) -> 'UnaryOp':
        """符号函数：+1, -1, 0。"""
        return UnaryOp('sign', self)

    def abs(self) -> 'UnaryOp':
        """绝对值。"""
        return UnaryOp('abs', self)

    def sqrt(self) -> 'UnaryOp':
        """平方根。"""
        return UnaryOp('sqrt', self)

    def neg(self) -> 'UnaryOp':
        """取负。"""
        return UnaryOp('neg', self)

    # ── 便利方法：横截面算子 ──

    def cs_zscore(self) -> 'CrossSectionalOp':
        """横截面 z-score 标准化（逐时间点）。"""
        return CrossSectionalOp('cs_zscore', self)

    def cs_rank(self) -> 'CrossSectionalOp':
        """横截面排名（从小到大，0~1 归一化）。"""
        return CrossSectionalOp('cs_rank', self)

    def cs_spearman(self, other: 'FactorExpr') -> 'CrossSectionalBinaryOp':
        """截面 Spearman 秩相关系数：self 与 other 逐时间点计算。"""
        return CrossSectionalBinaryOp('cs_spearman', self, other)


# ═════════════════════════════════════════════════════════════════════════════
# 辅助：将标量/ndarray 转为 ConstExpr
# ═════════════════════════════════════════════════════════════════════════════

def _to_expr(value: Any) -> FactorExpr:
    """将非 FactorExpr 值包装为 ConstExpr，将 Parameter 转为 ParamRef。"""
    if isinstance(value, FactorExpr):
        return value
    from tools.parameters.Parameter import Parameter
    if isinstance(value, Parameter):
        return ParamRef(value)
    return ConstExpr(value)  # type: ignore[arg-type]


# ═════════════════════════════════════════════════════════════════════════════
# Layer 1.5: 多元算子基类
# ═════════════════════════════════════════════════════════════════════════════

class OperandExpr(FactorExpr):
    """
    多元算子基类 — 所有含有子表达式的节点继承此类。

    核心设计：
      - __init__(op, *operands) 存储操作名和子表达式元组
      - _operands 属性自动从 self.operands 派生
      - evaluate() 递归求值所有子表达式 → 调用 _apply_op(values)
      - 子类只需覆盖 _apply_op() 和展示方法（op_name/to_latex/_get_alias）

    dependencies / param_deps / _collect_params_ordered
    均从 _operands 自动派生，无需子类覆盖。
    """

    def __init__(self, op: str, *operands: 'FactorExpr'):
        self.op = op
        self.operands: Tuple[FactorExpr, ...] = operands

    @property
    def _operands(self) -> Sequence['FactorExpr']:
        return self.operands

    @property
    def dependencies(self) -> Set['FactorExpr']:
        deps: Set['FactorExpr'] = set()
        for opnd in self._operands:
            deps.add(opnd)
            deps.update(opnd.dependencies)
        return deps

    @property
    def param_deps(self) -> Set['Parameter']:
        deps: Set['Parameter'] = set()
        for opnd in self._operands:
            deps |= opnd.param_deps
        return deps

    @property
    def ordered_param_deps(self) -> List['Parameter']:
        seen: Set['Parameter'] = set()
        result: List['Parameter'] = []
        self._collect_params_ordered(seen, result)
        return result

    def _collect_params_ordered(self, seen: Set['Parameter'], result: List['Parameter']):
        for opnd in self._operands:
            opnd._collect_params_ordered(seen, result)

    def resolve(self, *args, **kwargs) -> 'FactorExpr':
        resolved_operands = [opnd.resolve(*args, **kwargs) for opnd in self._operands]
        return type(self)(self.op, *resolved_operands)

    # ── 通用求值 ──

    def evaluate(self, products: Sequence['Product'], freq: DataFreq,
                 source: Optional['DataSource'] = None,
                 cache: Optional[Dict['FactorExpr', pd.DataFrame]] = None,
                 preloaded: Optional[Dict[Any, pd.DataFrame]] = None,
                 *args, **kwargs) -> pd.DataFrame:
        # ── 中间因子：先查 FactorData 全局缓存，命中则直接返回 ──
        if self._is_intermediate:
            from tools.factors.FactorData import FactorData
            structural_hash = str(self._structural_key())
            existing = FactorData.get_by_hash(structural_hash)
            if existing is not None and existing.source_table is not None \
                    and not existing.source_table.empty:
                return existing.source_table

        if cache is not None and self in cache:
            return cache[self]

        values = [opnd.evaluate(products, freq, source=source, cache=cache, preloaded=preloaded)
                  for opnd in self.operands]
        result = self._apply_op(values)

        if self._is_intermediate:
            # 存入 FactorData（UniqueObject 去重），不在 df_cache 留副本
            from tools.factors.FactorData import FactorData
            FactorData(self, result)
        elif cache is not None:
            cache[self] = result

        return result

    def _apply_op(self, values: List[Any]) -> pd.DataFrame:
        """子类覆盖：对已求值的 operands DataFrame 执行核心运算。"""
        raise NotImplementedError

    # ── 展示方法 ──

    @property
    def op_name(self) -> str:
        return self.op.upper()

    def to_latex(self) -> str:
        parts = [opnd.to_latex() for opnd in self.operands]
        return f'\\text{{{self.op}}}({", ".join(parts)})'

    def _get_alias(self) -> str:
        parts = [opnd._get_alias() for opnd in self.operands]
        return f"{self.op.upper()}_{'_'.join(parts)}"

    def __repr__(self) -> str:
        parts = [repr(opnd) for opnd in self.operands]
        return f"{self.op}({', '.join(parts)})"

    # ── 结构等价（FactorData 去重 key） ──

    def _structural_key(self) -> tuple:
        """
        OperandExpr 的结构 key。

        子类可通过覆盖 _structural_extra() 添加 op 之外的结构信息
        （如 RollingOp 需要 window, ShiftOp 需要 periods）。

        对称运算（add, mul, max, min, and, or, eq, ne,
        cs_spearman, cs_corr, cs_cov）的 operands 排序后取 key，
        保证 a+b ≡ b+a, max(a,b,c) ≡ max(c,a,b) 等。
        """
        type_tag = type(self).__name__
        op_tag = self.op
        op_keys_raw = [opnd._structural_key() for opnd in self._operands]
        if op_tag in FactorExpr._SYMMETRIC_OPS:
            op_keys = tuple(sorted(op_keys_raw, key=str))
        else:
            op_keys = tuple(op_keys_raw)
        extra = self._structural_extra()
        return (type_tag, op_tag, op_keys) + extra

    def _structural_extra(self) -> tuple:
        """子类覆盖：返回除 op + operands 外的额外结构信息。"""
        return ()


# ═════════════════════════════════════════════════════════════════════════════
# Layer 2: 叶子节点
# ═════════════════════════════════════════════════════════════════════════════

class ColumnRef(FactorExpr):
    """
    数据列引用 — 表达式树的叶子节点。

    示例：
        close = ColumnRef(DataColumn.CLOSE_ADJUSTED)
        high  = ColumnRef(DataColumn.HIGH_ADJUSTED)
        vol   = ColumnRef(DataColumn.VOLUME)

    运行时通过 product.{freq} 获取数据，source 参数选择数据源。
    """

    def __init__(self, column: DataColumn):
        self.column = column

    @property
    def required_columns(self) -> Set[str]:
        """此列引用所需的数据列名（用于校验数据源是否兼容）。"""
        return {self.column.name, self.column.value}

    def _select_source(self, product: 'Product', freq: DataFreq,
                       source: Optional['DataSource'] = None) -> Optional['DataSource']:
        """
        为给定品种选择数据源。返回 None 表示无需指定（DataMeta 使用自己的加载逻辑）。

        - 若 source 已指定：校验该品种在此 source+freq 下是否有数据
        - 若未指定：遍历 DataSource 找到第一个可用且包含所需列的源
        - 若无注册的数据源：返回 None，由 DataMeta 自行加载
        """
        from tools.data.DataSource import DataSource as DS

        if source is not None and source.freq == freq and product in source:
            return source
        
        available_sources = getattr(product, freq.name).list_available_sources()
        if available_sources:
            return available_sources[0]
        else:
            return None

    def evaluate(self, products: Sequence['Product'], freq: DataFreq,
                 source: Optional['DataSource'] = None,
                 cache: Optional[Dict[FactorExpr, pd.DataFrame]] = None,
                 preloaded: Optional[Dict[Any, pd.DataFrame]] = None) -> pd.DataFrame:
        if cache is not None and self in cache:
            return cache[self]

        from tools.data.DataMeta import DataMeta

        series_dict = {}
        for p in products:
            # 优先使用预加载数据
            if preloaded is not None:
                preload_key = (p, freq.name)
                preloaded_df = preloaded.get(preload_key)
                if preloaded_df is not None and self.column.name in preloaded_df.columns:
                    series_dict[p] = preloaded_df[self.column.name]
                    continue

            dm: DataMeta = getattr(p, freq.name)
            if source is not None:
                try:
                    ds = dm.set_current_source(source)
                except ValueError as e:
                    raise Warning(f"ColumnRef: source {source.alias} is not compatible with product {p.name} at freq {freq.name}") from e
            if dm.next_available_source() is None:
                continue  # 无可用数据源，跳过此品种
            col_name = self.column.name   # 如 'CLOSE_ADJUSTED' for CA

            # 使用 get_and_adjust_cols 确保复权列（如 CLOSE_ADJUSTED）被自动计算
            data = dm.get_and_adjust_cols([col_name], copy=False)
            if data.empty:
                continue
            series_dict[p] = data[col_name]

        result = pd.concat(series_dict, axis=1)
        result.columns = list(series_dict.keys())

        if cache is not None:
            cache[self] = result
        return result

    @property
    def op_name(self) -> str:
        return self.column.value

    def to_latex(self) -> str:
        col_to_latex = {
            'O': 'O_t', 'H': 'H_t', 'L': 'L_t', 'C': 'C_t',
            'OA': '\\tilde{O}_t', 'HA': '\\tilde{H}_t',
            'LA': '\\tilde{L}_t', 'CA': '\\tilde{C}_t',
            'V': 'V_t', 'OI': 'OI_t',
        }
        return col_to_latex.get(self.column.value) or self.column.value

    def _get_alias(self) -> str:
        return self.column.value

    def _structural_key(self) -> tuple:
        return ('ColumnRef', self.column)

    def __repr__(self) -> str:
        return f"ColumnRef({self.column.name})"

class ParamRef(FactorExpr):
    """
    参数引用 — 表达式树的叶子节点，运行时从 FactorFamily 注册表取参数值。

    示例：
        window_param = WindowParam('W', 5)            # 2. WindowParam 来自 tools/parameters
        close_ma = ColumnRef(DataColumn.CLOSE_ADJUSTED).ma(window_param)

        # 等价于：close_ma = CLOSE.ma(5)，但窗口长度由外部参数化

    支持的类型：
      - DataColumnParam: 值会被 rectify 为 DataColumn 后用于列查找
      - WindowParam: 值作为窗口参数传入 RollingOp
      - 任意 Parameter: 值直接作为标量参与表达式计算
    """

    def __init__(self, param: 'Parameter'):
        self.param = param

    @property
    def param_deps(self) -> Set['Parameter']:
        return {self.param}

    def _collect_params_ordered(self, seen: Set['Parameter'], result: List['Parameter']):
        if self.param not in seen:
            seen.add(self.param)
            result.append(self.param)

    def evaluate(self, *args, **kwargs) -> pd.DataFrame:
        raise RuntimeError("ParamRef.evaluate() 不得调用; 请先调用 resolve(param_values) 将 ParamRef 转为 ConstExpr/ColumnRef 后再求值")

    def resolve(self, param_values: dict | None = None, *args, **kwargs) -> FactorExpr:
        """从宿主对象的注册表中取出当前参数值。若提供 param_values 则优先从中查找。"""
        if param_values is not None and self.param.alias in param_values:
            value = param_values[self.param.alias]
            from tools.parameters import DataColumnParam
            if isinstance(self.param, DataColumnParam):
                return ColumnRef(DataColumn(value))
            else:
                return ConstExpr(value)
        return ConstExpr(self.param.default_value)

    @property
    def op_name(self) -> str:
        return f"${{{self.param.alias}}}"

    def to_latex(self) -> str:
        """LaTeX 变量名。ParamRef 的参数名作为基础变量，如 'P' → P_t。"""
        return f"{self.param.alias}_{{t}}"

    def _get_alias(self) -> str:
        return f"P{self.param.alias}"

    def __repr__(self) -> str:
        return f"ParamRef({self.param.alias})"

    def _structural_key(self) -> tuple:
        return ('ParamRef', self.param.alias)

class ConstExpr(FactorExpr):
    """
    常量表达式 — 标量、固定值或窗口/位移参数的叶子节点。

    当 value 是 int/float/ndarray 时 → 参与表达式运算，evaluate() 返回 self
    （由 CompositeExpr._apply_op 提取 .value 后内联处理）。

    当 value 是 pd.Timedelta/DataFreq 时 → 窗口/位移参数，
    evaluate() 直接返回 bar 数（int）。
    """

    def __init__(self, value: Union[int, float, np.ndarray]):
        self.value = value

    def evaluate(self, freq: DataFreq,
                 dm: Optional['DataMeta'] = None, *args, **kwargs
                 ) -> pd.DataFrame:
        if isinstance(self.value, (pd.Timedelta, DataFreq)):
            if dm is None:
                raise ValueError("ConstExpr 以 Timedelta/DataFreq 为 value 需要 DataMeta 以计算 day_periods")
            return cast(pd.DataFrame, _resolve_window(self.value, freq, dm))
        # 标量/数组常量：返回 self，由 CompositeExpr._apply_op 提取 value 后内联处理
        return cast(pd.DataFrame, self)

    @property
    def op_name(self) -> str:
        return f"const({self.value})"

    def to_latex(self) -> str:
        return str(self.value)

    def _get_alias(self) -> str:
        v = self.value
        if isinstance(v, (int, float)):
            return str(v).replace('.', 'd').replace('-', 'N')
        return 'const'

    def __repr__(self) -> str:
        return f"ConstExpr({self.value})"

    def _structural_key(self) -> tuple:
        v = self.value
        if isinstance(v, np.ndarray):
            return ('ConstExpr', v.tobytes())
        return ('ConstExpr', v)


# ═════════════════════════════════════════════════════════════════════════════
# Layer 3: 一元算子
# ═════════════════════════════════════════════════════════════════════════════

class UnaryOp(OperandExpr):
    """
    一元算子：LOG, SIGN, ABS, NEG, NOT, SQRT 等。
    """

    def __init__(self, op: str, operand: FactorExpr):
        super().__init__(op, operand)

    @property
    def operand(self) -> FactorExpr:
        return self.operands[0]

    def _apply_op(self, values: List[Any]) -> pd.DataFrame:
        x = values[0]
        _OP_MAP = {
            'log': np.log,
            'sign': np.sign,
            'abs': np.abs,
            'neg': np.negative,
            'not': np.logical_not,
            'sqrt': np.sqrt,
        }
        return _OP_MAP[self.op](x)

    def to_latex(self) -> str:
        operand_latex = self.operand.to_latex()
        _LATEX_MAP = {
            'log': f'\\ln({operand_latex})',
            'sign': f'\\operatorname{{sgn}}({operand_latex})',
            'abs': f'|{operand_latex}|',
            'neg': f'-({operand_latex})',
            'not': f'\\neg({operand_latex})',
            'sqrt': f'\\sqrt{{{operand_latex}}}',
        }
        return _LATEX_MAP.get(self.op, f'{self.op}({operand_latex})')

    def _get_alias(self) -> str:
        return f"{self.op}_{self.operand._get_alias()}"

    def __repr__(self) -> str:
        return f"{self.op}({self.operand})"


# ═════════════════════════════════════════════════════════════════════════════
# Layer 4: 滚动窗口算子
# ═════════════════════════════════════════════════════════════════════════════

class RollingOp(OperandExpr):
    """
    滚动窗口算子抽象基类。

    operands = (window, data1, data2, ...)
    window 是第一 operand（ConstExpr 或 ParamRef），数据 operands 紧随其后。

    子类只需声明操作数和核心滚动运算逻辑。
    """

    @property
    def window(self) -> 'FactorExpr':
        """第一 operand：窗口参数。"""
        return self.operands[0]

    # ── 算子映射：op → lambda(*series_or_dfs, window) ──

    _OP_MAP = {
        'ma':     lambda s, w: s.rolling(w, min_periods=max(1, w // 2)).mean(),
        'std':    lambda s, w: s.rolling(w, min_periods=max(1, w // 2)).std(),
        'var':    lambda s, w: s.rolling(w, min_periods=max(1, w // 2)).var(),
        'min':    lambda s, w: s.rolling(w, min_periods=1).min(),
        'max':    lambda s, w: s.rolling(w, min_periods=1).max(),
        'sum':    lambda s, w: s.rolling(w, min_periods=1).sum(),
        'ema':    lambda s, w: s.ewm(span=w, min_periods=max(1, w // 2)).mean(),
        'skew':   lambda s, w: s.rolling(w, min_periods=max(1, w // 2)).skew(),
    }

    def _apply_rolling(self, window: int, *dfs: pd.DataFrame,
                       freq: DataFreq) -> pd.DataFrame:
        # argmax/argmin：全向量化，不依赖 rolling()
        if self.op in ('argmax', 'argmin'):
            return _rolling_argmaxmin(dfs[0], window, self.op)

        if self.op in self._OP_MAP:
            func = self._OP_MAP[self.op]
            return dfs[0].apply(func, axis=0, args=(window,))

        # 二元
        if self.op in ('corr', 'cov'):
            left_df, right_df = dfs
            result = pd.DataFrame(index=left_df.index, columns=left_df.columns, dtype=float)
            for col in left_df.columns:
                if self.op == 'corr':
                    result[col] = left_df[col].rolling(window).corr(right_df[col])
                else:
                    result[col] = left_df[col].rolling(window).cov(right_df[col])
            return result

        raise ValueError(f"Unknown rolling op: {self.op}")

    # ── 展示方法 ──

    @property
    def operand(self) -> FactorExpr:
        """数据操作数（向后兼容，一元时使用）。"""
        return self.operands[1]

    def _window_str(self) -> str:
        """窗口的字符串表示，用于 op_name / alias / latex。"""
        w = self.window
        if isinstance(w, ConstExpr):
            return str(w.value)
        return str(w).replace(' ', '')

    @property
    def op_name(self) -> str:
        return f"{self.op.upper()}_{self._window_str()}"

    def to_latex(self) -> str:
        w_str = self._window_str()
        if len(self.operands) == 2:
            # 一元
            operand_latex = self.operands[1].to_latex()
            _LATEX_MAP = {
                'ma': f'\\text{{MA}}_{{{w_str}}}({operand_latex})',
                'std': f'\\sigma_{{{w_str}}}({operand_latex})',
                'var': f'\\sigma^2_{{{w_str}}}({operand_latex})',
                'min': f'\\min_{{{w_str}}}({operand_latex})',
                'max': f'\\max_{{{w_str}}}({operand_latex})',
                'sum': f'\\sum_{{{w_str}}}({operand_latex})',
                'ema': f'\\text{{EMA}}_{{{w_str}}}({operand_latex})',
                'skew': f'\\text{{Skew}}_{{{w_str}}}({operand_latex})',
                'argmax': f'\\text{{ArgMax}}_{{{w_str}}}({operand_latex})',
                'argmin': f'\\text{{ArgMin}}_{{{w_str}}}({operand_latex})',
            }
            return _LATEX_MAP.get(self.op, f'{self.op}_{{{w_str}}}({operand_latex})')
        else:
            left_latex = self.operands[1].to_latex()
            right_latex = self.operands[2].to_latex()
            return f'\\text{{{self.op.capitalize()}}}_{{{w_str}}}({left_latex}, {right_latex})'

    def _get_alias(self) -> str:
        parts = [self.op]
        for opnd in self.operands[1:]:
            parts.append(opnd._get_alias())
        parts.append(f"W{self._window_str()}")
        return "_".join(parts)

    def __repr__(self) -> str:
        w_str = self._window_str()
        if len(self.operands) == 2:
            return f"{self.op}({self.operands[1]}, {w_str})"
        else:
            return f"{self.op}({self.operands[1]}, {self.operands[2]}, {w_str})"

    def evaluate(self, products: Sequence['Product'], freq: DataFreq,
                 source: Optional['DataSource'] = None,
                 cache: Optional[Dict['FactorExpr', pd.DataFrame]] = None,
                 preloaded: Optional[Dict[Any, pd.DataFrame]] = None) -> pd.DataFrame:
        if cache is not None and self in cache:
            return cache[self]

        # 先求值数据 operands（非 window）
        data_vals = [opnd.evaluate(products, freq, source=source, cache=cache, preloaded=preloaded)
                     for opnd in self.operands[1:]]

        # 从第一个产品拿 DataMeta，用于窗口参数中的 day_periods 计算
        from tools.data.DataMeta import DataMeta
        dm: DataMeta = getattr(products[0], freq.name)

        # 求窗口值（ConstExpr.evaluate 需要 DataMeta 来计算 day_periods）
        window_val = self.operands[0].evaluate(products, freq, source=source,
                                                cache=cache, preloaded=preloaded, dm=dm)
        result = self._apply_rolling(window_val, *data_vals, freq=freq)  # type: ignore[arg-type]

        if cache is not None:
            cache[self] = result
        return result

class ShiftOp(OperandExpr):
    """
    位移算子：SHIFT(periods, x) 即前 N 期的 x 值。

    operands = (periods, operand)
    periods 是第一 operand（ConstExpr 或 ParamRef），operand 是第二 operand。
    """

    def __init__(self, op: str, periods: Union[int, str, pd.Timedelta, 'Parameter', 'FactorExpr'],
                 operand: 'FactorExpr'):
        super().__init__(op, _to_expr(periods), operand)

    @property
    def periods(self) -> 'FactorExpr':
        return self.operands[0]

    @property
    def operand(self) -> 'FactorExpr':
        return self.operands[1]

    # ── evaluate：覆盖 OperandExpr 默认实现 ──

    def evaluate(self, products: Sequence['Product'], freq: DataFreq,
                 source: Optional['DataSource'] = None,
                 cache: Optional[Dict[FactorExpr, pd.DataFrame]] = None,
                 preloaded: Optional[Dict[Any, pd.DataFrame]] = None) -> pd.DataFrame:
        if cache is not None and self in cache:
            return cache[self]

        # 先求 operand（DataFrame）
        operand_val = self.operands[1].evaluate(products, freq, source=source,
                                                  cache=cache, preloaded=preloaded)

        # 从第一个产品拿 DataMeta，用于 periods 参数中的 day_periods 计算
        from tools.data.DataMeta import DataMeta
        dm: DataMeta = getattr(products[0], freq.name)

        periods_val = self.operands[0].evaluate(products, freq, source=source,
                                                  cache=cache, preloaded=preloaded, dm=dm)

        result = operand_val.shift(periods_val)  # type: ignore[arg-type]

        if cache is not None:
            cache[self] = result
        return result

    # ── 展示方法 ──

    @property
    def op_name(self) -> str:
        p = self.periods
        label = str(p.value) if isinstance(p, ConstExpr) else str(p)
        return f"SHIFT_{label}"

    def to_latex(self) -> str:
        operand_latex = self.operand.to_latex()
        p_expr = self.periods
        if isinstance(p_expr, ConstExpr):
            p_label = str(p_expr.value)
        else:
            p_label = str(p_expr)
        # 如果是列/参数引用且形如 "X_{t}"，替换为自然下标 "X_{t - NS}"
        if isinstance(self.operand, (ColumnRef, ParamRef)) and operand_latex.endswith('_{t}'):
            base = operand_latex[:-3]  # 去掉 "{t}"，保留 "X_"
            return base + '{t - ' + p_label + '}'
        return f"\\text{{SHIFT}}_{{{p_label}}}({operand_latex})"

    def _get_alias(self) -> str:
        p_expr = self.periods
        p = str(p_expr.value) if isinstance(p_expr, ConstExpr) else str(p_expr).replace(' ', '')
        return f"shift_{self.operand._get_alias()}_{p}"

    def __repr__(self) -> str:
        return f"shift({self.operand}, {self.periods})"


def _rolling_argmaxmin(
    df: pd.DataFrame,
    window: int,
    op: str,
    normalize: bool = True,
) -> pd.DataFrame:
    """用 sliding_window_view 对 DataFrame 每列计算滚动 argmax 或 argmin。"""
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")

    n_rows = len(df)
    if n_rows < window:
        return pd.DataFrame(np.full((n_rows, df.shape[1]), np.nan),
                            index=df.index, columns=df.columns)

    arr = df.to_numpy(dtype=float)
    windows = np.lib.stride_tricks.sliding_window_view(arr, window, axis=0)
    reversed_view = windows[..., ::-1]
    if op == 'argmax':
        pos = (window - 1) - np.argmax(reversed_view, axis=-1)
    elif op == 'argmin':
        pos = (window - 1) - np.argmin(reversed_view, axis=-1)
    else:
        raise ValueError(f"Invalid op: {op}")

    pos = pos.astype(float)
    if normalize and window > 1:
        pos = pos / (window - 1)

    nan_rows = np.full((window - 1, df.shape[1]), np.nan)
    result = np.vstack([nan_rows, pos])
    return pd.DataFrame(result, index=df.index, columns=df.columns)


def _resolve_window(window_val: Union[pd.Timedelta, 'DataFreq'], freq: DataFreq,
                    dm: 'DataMeta') -> int:
    """将时间窗口/位移参数转为 bar 数量（整数）。

    规则：
      - day-multiple 时间跨度（如 '5d'）：从 DataMeta.day_periods 缓存 × 天数
      - 其他 Timedelta：要求整除当前数据频率，返回整数倍数
    """
    td = window_val if isinstance(window_val, pd.Timedelta) else window_val.value
    total_sec = td.total_seconds()

    window_freq = DataFreq(td)
    if window_freq.is_day_multiple():
        day_periods = dm.day_periods
        day_count = int(total_sec / pd.Timedelta('1day').total_seconds())
        return day_periods * day_count

    freq_sec = freq.value.total_seconds()
    if total_sec % freq_sec != 0:
        raise ValueError(
            f"{window_val} is not divisible by data frequency {freq.name} "
            f"({total_sec}s vs {freq_sec}s per bar)"
        )
    return int(total_sec / freq_sec)


# ═════════════════════════════════════════════════════════════════════════════
# Layer 5: 横截面算子
# ═════════════════════════════════════════════════════════════════════════════

class CrossSectionalOp(OperandExpr):
    """
    一元横截面算子：CS_ZSCORE, CS_RANK 等。

    在每个时间点对横截面（所有品种）进行聚合计算。
    """

    def __init__(self, op: str, operand: FactorExpr):
        super().__init__(op, operand)

    @property
    def operand(self) -> FactorExpr:
        return self.operands[0]

    def _apply_op(self, values: List[Any]) -> pd.DataFrame:
        x = values[0]
        if self.op == 'cs_zscore':
            mean = x.mean(axis=1)
            std = x.std(axis=1)
            std = std.replace(0, np.nan)
            return x.sub(mean, axis=0).div(std, axis=0)
        elif self.op == 'cs_rank':
            return x.rank(axis=1, pct=True) - 0.5
        else:
            raise ValueError(f"Unknown cross-sectional op: {self.op}")

    def to_latex(self) -> str:
        operand_latex = self.operand.to_latex()
        _LATEX_MAP = {
            'cs_zscore': f'Z({operand_latex})',
            'cs_rank': f'\\text{{Rank}}({operand_latex})',
        }
        return _LATEX_MAP.get(self.op, f'\\text{{{self.op}}}({operand_latex})')

    def _get_alias(self) -> str:
        return f"{self.op}_{self.operand._get_alias()}"

    def __repr__(self) -> str:
        return f"{self.op}({self.operand})"


# ═════════════════════════════════════════════════════════════════════════════
# 二元横截面算子
# ═════════════════════════════════════════════════════════════════════════════

class CrossSectionalBinaryOp(OperandExpr):
    """
    二元横截面算子：cs_spearman 等。
    """

    def __init__(self, op: str, left: FactorExpr, right: FactorExpr):
        super().__init__(op, left, right)

    @property
    def left(self) -> FactorExpr:
        return self.operands[0]

    @property
    def right(self) -> FactorExpr:
        return self.operands[1]

    def _apply_op(self, values: List[Any]) -> pd.DataFrame:
        left_df, right_df = values[0], values[1]
        if self.op == 'cs_spearman':
            return self._apply_spearman(left_df, right_df)
        raise ValueError(f"Unknown cross-sectional binary op: {self.op}")

    @staticmethod
    def _apply_spearman(left_df: pd.DataFrame, right_df: pd.DataFrame) -> pd.DataFrame:
        import numpy as np
        common_idx = left_df.index.intersection(right_df.index)
        ic_values = []
        idx_list = []
        for idx in common_idx:
            l = left_df.loc[idx]
            r = right_df.loc[idx]
            if isinstance(l, pd.DataFrame):
                l = l.iloc[0]
            if isinstance(r, pd.DataFrame):
                r = r.iloc[0]
            valid = l.notna() & r.notna()
            if valid.sum() > 1 and l[valid].nunique() > 1 and r[valid].nunique() > 1:
                with np.errstate(invalid='ignore'):
                    ic_values.append(pd.Series(l[valid]).corr(r[valid], method='spearman'))
            else:
                ic_values.append(np.nan)
            idx_list.append(idx)
        result = pd.DataFrame({'IC': ic_values}, index=pd.Index(idx_list))
        result.index.names = left_df.index.names
        return result

    def to_latex(self) -> str:
        left_latex = self.left.to_latex()
        right_latex = self.right.to_latex()
        if self.op == 'cs_spearman':
            return f'\\rho_s({left_latex}, {right_latex})'
        return f'\\text{{{self.op}}}({left_latex}, {right_latex})'

    def _get_alias(self) -> str:
        return f"{self.op}_{self.left._get_alias()}_{self.right._get_alias()}"

    def __repr__(self) -> str:
        return f"{self.op}({self.left}, {self.right})"


# ═════════════════════════════════════════════════════════════════════════════
# Layer 6: 复合表达式（二元运算树节点）
# ═════════════════════════════════════════════════════════════════════════════

class CompositeExpr(OperandExpr):
    """
    复合表达式 — 元素级多元运算。

    支持：
      - add, sub, mul, div（算术）
      - gt, lt, ge, le, eq, ne（比较）
      - and, or（逻辑）
      - max, min, pow（多元聚合）
      - neg, abs, not（一元）
    """

    _ARITH_OPS = {
        'add': ('+', lambda a, b: a + b),
        'sub': ('-', lambda a, b: a - b),
        'mul': ('*', lambda a, b: a * b),
        'div': ('/', lambda a, b: a / b),
    }

    _COMPARE_OPS = {
        'gt': ('>', lambda a, b: a > b),
        'lt': ('<', lambda a, b: a < b),
        'ge': ('>=', lambda a, b: a >= b),
        'le': ('<=', lambda a, b: a <= b),
        'eq': ('==', lambda a, b: a == b),
        'ne': ('!=', lambda a, b: a != b),
    }

    _LOGIC_OPS = {
        'and': ('&', lambda a, b: a & b),
        'or': ('|', lambda a, b: a | b),
    }

    _UNARY_OPS = {
        'neg': ('-', lambda a: -a),
        'abs': ('abs', lambda a: abs(a)),
        'not': ('~', lambda a: ~a),
    }

    def __init__(self, op: str, *operands: FactorExpr):
        super().__init__(op, *operands)

    @staticmethod
    def _fold_const(op: str, operands: Tuple['ConstExpr', ...]) -> Optional['ConstExpr']:
        """
        常量折叠：当所有 operands 都是 ConstExpr 时，尝试直接计算。

        返回 ConstExpr 或 None（无法折叠时）。
        """
        from tools.parameters.Parameter import Parameter
        values = [opnd.value for opnd in operands]
        try:
            if op == 'add':
                result = values[0] + values[1]
            elif op == 'sub':
                result = values[0] - values[1]
            elif op == 'mul':
                result = values[0] * values[1]
            elif op == 'div':
                result = values[0] / values[1]
            elif op == 'neg':
                result = -values[0]
            elif op == 'abs':
                result = abs(values[0])
            else:
                return None
            if isinstance(result, Parameter):
                return None
            return ConstExpr(result)
        except Exception:
            return None

    def _apply_op(self, values: List[Any]) -> pd.DataFrame:
        """根据 op 类型执行实际运算（由 OperandExpr.evaluate 调用）。"""
        v = values

        # 一元算
        if self.op in self._UNARY_OPS:
            _, fn = self._UNARY_OPS[self.op]
            return fn(v[0])

        # 二元算
        a, b = v[0], v[1]

        # 如果 b 是 ConstExpr，提取标量值
        if isinstance(self.operands[1], ConstExpr):
            b = self.operands[1].value
        if isinstance(self.operands[0], ConstExpr):
            a = self.operands[0].value

        if self.op in self._ARITH_OPS:
            _, fn = self._ARITH_OPS[self.op]
            return fn(a, b)

        if self.op in self._COMPARE_OPS:
            _, fn = self._COMPARE_OPS[self.op]
            return fn(a, b)

        if self.op in self._LOGIC_OPS:
            _, fn = self._LOGIC_OPS[self.op]
            return fn(a, b)

        # 非 DataFrame 回退（仅当 ConstExpr 标量被提取后两个都是标量时触发）
        if not isinstance(a, pd.DataFrame):
            if self.op == 'max':
                return np.maximum(a, b)  # type: ignore[return-value]
            if self.op == 'min':
                return np.minimum(a, b)  # type: ignore[return-value]
            if self.op == 'pow':
                return a ** b  # type: ignore[return-value]
            raise ValueError(f"Unknown op: {self.op}")

        # 经过上面的 isinstance 守卫后，a 必定是 DataFrame
        a_df: pd.DataFrame = a

        if self.op == 'max':
            if np.isscalar(b):
                return a_df.clip(lower=b)  # type: ignore[arg-type]
            return pd.DataFrame(np.maximum(a_df.values, b.values),  # type: ignore[union-attr]
                                index=a_df.index, columns=a_df.columns)

        if self.op == 'min':
            if np.isscalar(b):
                return a_df.clip(upper=b)  # type: ignore[arg-type]
            return pd.DataFrame(np.minimum(a_df.values, b.values),  # type: ignore[union-attr]
                                index=a_df.index, columns=a_df.columns)

        if self.op == 'pow':
            return a_df ** b  # type: ignore[return-value]

        raise ValueError(f"Unknown op: {self.op}")

    @property
    def op_name(self) -> str:
        if self.op in self._ARITH_OPS:
            return self._ARITH_OPS[self.op][0]
        if self.op in self._COMPARE_OPS:
            return self._COMPARE_OPS[self.op][0]
        if self.op in self._LOGIC_OPS:
            return self._LOGIC_OPS[self.op][0]
        if self.op in self._UNARY_OPS:
            return self._UNARY_OPS[self.op][0]
        if self.op in ('max', 'min'):
            return self.op
        return self.op

    def to_latex(self) -> str:
        if self.op in self._UNARY_OPS:
            symbol, _ = self._UNARY_OPS[self.op]
            return f'{symbol}({self.operands[0].to_latex()})'

        left = self.operands[0].to_latex()
        right = self.operands[1].to_latex()

        if self.op in self._ARITH_OPS:
            symbol = self._ARITH_OPS[self.op][0]
            if self.op == 'div':
                return f'\\frac{{{left}}}{{{right}}}'
            return f'({left} {symbol} {right})'

        if self.op in self._COMPARE_OPS:
            symbol = self._COMPARE_OPS[self.op][0]
            return f'({left} {symbol} {right})'

        if self.op in self._LOGIC_OPS:
            symbol = self._LOGIC_OPS[self.op][0]
            return f'({left} {symbol} {right})'

        if self.op == 'max':
            return f'\\max({left}, {right})'
        if self.op == 'min':
            return f'\\min({left}, {right})'

        if self.op == 'pow':
            return f'{{{left}}}^{{{right}}}'

        return f'{self.op}({left}, {right})'

    def _get_alias(self) -> str:
        op_aliases = {
            'add': 'ADD', 'sub': 'SUB', 'mul': 'MUL', 'div': 'DIV',
            'gt': 'GT', 'lt': 'LT', 'ge': 'GE', 'le': 'LE',
            'eq': 'EQ', 'ne': 'NE',
            'and': 'AND', 'or': 'OR',
            'neg': 'NEG', 'abs': 'ABS', 'not': 'NOT',
        }
        op_alias = op_aliases.get(self.op, self.op.upper())
        parts = [opnd._get_alias() for opnd in self.operands]
        return f"{op_alias}_{'_'.join(parts)}"

    def __repr__(self) -> str:
        parts = [repr(opnd) for opnd in self.operands]
        if len(parts) == 1:
            return f"{self.op}({parts[0]})"
        return f"({parts[0]} {self.op_name} {parts[1]})"


# ═════════════════════════════════════════════════════════════════════════════
# 顶层便利函数：max / min 多元聚合
# ═════════════════════════════════════════════════════════════════════════════

def expr_max(*exprs: FactorExpr) -> FactorExpr:
    """多元逐元素最大值。"""
    if len(exprs) == 0:
        raise ValueError("expr_max requires at least one argument")
    if len(exprs) == 1:
        return exprs[0]
    result = exprs[0]
    for e in exprs[1:]:
        # 使用复合表达式节点
        result = _binary_max(result, e)
    return result


def expr_min(*exprs: FactorExpr) -> FactorExpr:
    """多元逐元素最小值。"""
    if len(exprs) == 0:
        raise ValueError("expr_min requires at least one argument")
    if len(exprs) == 1:
        return exprs[0]
    result = exprs[0]
    for e in exprs[1:]:
        result = _binary_min(result, e)
    return result


def _binary_max(a: FactorExpr, b: FactorExpr) -> FactorExpr:
    """逐元素 max = (a+b+|a-b|)/2。"""
    return (a + b + (a - b).abs()) * 0.5


def _binary_min(a: FactorExpr, b: FactorExpr) -> FactorExpr:
    """逐元素 min = (a+b-|a-b|)/2。"""
    return (a + b - (a - b).abs()) * 0.5


# ═════════════════════════════════════════════════════════════════════════════
# 预定义常用列引用（方便直接使用）
# ═════════════════════════════════════════════════════════════════════════════

OPEN = ColumnRef(DataColumn.OPEN_ADJUSTED)
HIGH = ColumnRef(DataColumn.HIGH_ADJUSTED)
LOW = ColumnRef(DataColumn.LOW_ADJUSTED)
CLOSE = ColumnRef(DataColumn.CLOSE_ADJUSTED)
VOLUME = ColumnRef(DataColumn.VOLUME)
TURNOVER = ColumnRef(DataColumn.TURNOVER)
OPEN_INTEREST = ColumnRef(DataColumn.OPEN_INTEREST)
VWAP = ColumnRef(DataColumn.VWAP)
SETTLE = ColumnRef(DataColumn.SETTLEMENT_PRICE)

# 原始（不复权）价格列
OPEN_RAW = ColumnRef(DataColumn.OPEN)
HIGH_RAW = ColumnRef(DataColumn.HIGH)
LOW_RAW = ColumnRef(DataColumn.LOW)
CLOSE_RAW = ColumnRef(DataColumn.CLOSE)


# ═════════════════════════════════════════════════════════════════════════════
# 信号对齐工具函数 & 表达式节点
# ═════════════════════════════════════════════════════════════════════════════

def signal_align(
    data: pd.DataFrame,
    freq: Any,
    basepoint: 'str|Callable' = 'last',
    daily_basepoint: 'str|None' = None,
    end_session_skip: bool = True,
    end_session_gap: pd.Timedelta = pd.Timedelta('3hours'),
) -> pd.DataFrame:
    """
    将原始数据对齐到等间隔信号时间点。

    参数：
        data           : 待对齐的 DataFrame（列=Product，行=MultiIndex 时间）
        freq           : 目标信号频率（如 '1d', '1h'）
        basepoint      : 基准点选择策略 'last'/'first'/callable
        daily_basepoint: 日倍频时的具体时间基准点（如 '15:00:00'），None 用 basepoint
        end_session_skip: 是否跳过盘间间隔（仅子日频生效）
        end_session_gap: 盘间间隔阈值

    返回：
        对齐后的 DataFrame，索引含 _SIGNAL@ 层级
    """
    import pandas as pd
    freq_dc = DataFreq(freq)
    bp = basepoint
    end_skip = end_session_skip
    end_gap = end_session_gap

    # 找到 freq 是其整数倍的索引层级（第一个匹配的）
    index_names = [str(n) for n in data.index.names]
    index_freqs = [DataFreq(n) for n in index_names]
    try:
        first_true_idx = next(
            (i for i, f in enumerate(index_freqs)
             if freq_dc.value.total_seconds() % f.value.total_seconds() == 0))
    except StopIteration:
        raise ValueError(
            f"频率 {freq_dc} 不是任何数据索引频率的整数倍")
    multiple = int(freq_dc.value.total_seconds() / index_freqs[first_true_idx].value.total_seconds())

    idx_name = index_names[first_true_idx]
    idx_series = data.index.get_level_values(idx_name).to_series().reset_index(drop=True)

    # 确定各组的基准点位置
    if freq_dc.is_day_multiple and daily_basepoint is not None:
        try:
            base_time = pd.Timestamp(daily_basepoint).time()
        except Exception:
            raise ValueError(
                f"Invalid time basepoint '{daily_basepoint}'. "
                f"Must be a time string like '09:01:00' or '15:00:00'")
        series = data.groupby(idx_name).transform(
            lambda x: pd.DatetimeIndex(x.index.get_level_values(-1)).time == base_time)
    elif isinstance(bp, str):
        bp_lower = bp.lower()
        if bp_lower == 'last':
            series = data.groupby(idx_name).cumcount(ascending=False) == 0
        elif bp_lower == 'first':
            series = data.groupby(idx_name).cumcount() == 0
        else:
            raise ValueError(
                f"Invalid basepoint '{bp}'. Must be 'last', 'first', or a callable")
    else:
        series = bp(data.groupby(idx_name))

    if not any(series):
        series = data.groupby(idx_name).cumcount(ascending=False) == 0
    assert isinstance(series, pd.Series) and series.dtype == bool, \
        "basepoint function must return a boolean Series"

    basepoint_pos = series.reset_index(drop=True).index[series]

    # 从基准点按 multiple 间隔取信号点
    if end_skip and isinstance(freq_dc.value, pd.Timedelta) and freq_dc.value < pd.Timedelta('1day'):
        last_col_name = index_names[-1]
        last_col = data.index.get_level_values(last_col_name).to_series().reset_index(drop=True)
        end_session_pos = last_col[last_col.shift(-1) - last_col >= end_gap].index
        signal_map_mask = basepoint_pos.isin({
            i
            for start, end in zip(
                [0] + (end_session_pos[:-1].values + 1).tolist(),
                end_session_pos
            )
            for i in range(start + multiple - 1, end + 1, multiple)
            if start + multiple - 1 <= end
        })
    else:
        idx = basepoint_pos.to_series().reset_index(drop=True).index
        signal_map_mask = (idx % multiple == multiple - 1)

    signal_pos = basepoint_pos[signal_map_mask]
    signal_map = idx_series.index.isin(signal_pos)

    # 构建新的索引
    signal_name = f'_SIGNAL@{freq_dc.name}'
    left_arrays = [
        data.index.get_level_values(index_names[i]).to_series().where(signal_map)
        for i in range(first_true_idx)
    ]
    signal_vals = idx_series.where(signal_map)
    right_arrays = [
        data.index.get_level_values(index_names[i]).to_series()
        for i in range(first_true_idx + 1, len(index_names))
    ]
    left_names = [str(n).split('@')[-1] for n in index_names[:first_true_idx]]
    right_names = [str(n).split('@')[-1] for n in index_names[first_true_idx + 1:]]
    new_index = pd.MultiIndex.from_arrays(
        left_arrays + [signal_vals] + right_arrays,
        names=left_names + [signal_name] + right_names
    ).dropna()

    result = data[signal_map].copy()
    result.index = new_index
    return result


# ═════════════════════════════════════════════════════════════════════════════
# 信号对齐表达式节点
# ═════════════════════════════════════════════════════════════════════════════

class SignalAlign(OperandExpr):
    """
    信号对齐表达式节点。

    将操作数表达式的求值结果对齐到等间隔信号时间点。
    这是一个一元算子：接收一个子表达式，evaluate 时先求子表达式，
    再对结果 DataFrame 做索引对齐。

    参数：
        operand         : 被包裹的因子表达式
        signal_freq     : 目标信号频率（如 '1d', '1h'，可以是 $F 参数的值）
        basepoint       : 基准点选择策略 'last'/'first'/callable，默认 'last'
        daily_basepoint : 日倍频时的具体时间基准点，None 则用 basepoint
        end_session_skip: 是否跳过盘间间隔（仅子日频生效），默认 True
        end_session_gap : 盘间间隔阈值，默认 3hours
    """

    def __init__(self, operand: FactorExpr, signal_freq: Any,
                 basepoint: 'str|Callable' = 'last',
                 daily_basepoint: 'str|None' = None,
                 end_session_skip: bool = True,
                 end_session_gap: pd.Timedelta = pd.Timedelta('3hours')):
        super().__init__('SIGNAL_ALIGN', operand)
        self.signal_freq = signal_freq
        self.basepoint = basepoint
        self.daily_basepoint = daily_basepoint
        self.end_session_skip = end_session_skip
        self.end_session_gap = end_session_gap
        # 保存最近一次求值前的原始数据（供 source_table 使用）
        self._raw_data: pd.DataFrame | None = None

    def _structural_extra(self) -> tuple:
        return ('signal_freq', str(self.signal_freq),
                'basepoint', str(self.basepoint),
                'daily_basepoint', str(self.daily_basepoint),
                'end_session_skip', self.end_session_skip,
                'end_session_gap', str(self.end_session_gap))

    def _apply_op(self, values: List[Any]) -> pd.DataFrame:
        data = values[0]
        self._raw_data = data  # 保存未对齐的原始数据
        return signal_align(
            data, self.signal_freq,
            basepoint=self.basepoint,
            daily_basepoint=self.daily_basepoint,
            end_session_skip=self.end_session_skip,
            end_session_gap=self.end_session_gap,
        )

    # ── 展示 ──

    @property
    def op_name(self) -> str:
        return f'SIGNAL@{self.signal_freq}'

    def _get_alias(self) -> str:
        inner = self.operands[0]._get_alias()
        return f'SIGNAL_{inner}'

    def to_latex(self) -> str:
        inner = self.operands[0].to_latex()
        return f'\\text{{SIGNAL}}_{{{self.signal_freq}}}({inner})'

    def __repr__(self) -> str:
        return f"SignalAlign({self.operands[0]!r}, freq={self.signal_freq!r})"
