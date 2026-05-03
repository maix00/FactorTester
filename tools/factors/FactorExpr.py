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
    TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union
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
    from tools.parameters.Parameter import Parameter


# ═════════════════════════════════════════════════════════════════════════════
# 工具函数：sliding_window_view 向量化滚动 argmax/argmin
# ═════════════════════════════════════════════════════════════════════════════

def _rolling_argmaxmin(
    df: pd.DataFrame,
    window: int,
    op: str,
    normalize: bool = True,
) -> pd.DataFrame:
    """
    用 sliding_window_view 对 DataFrame 每列计算滚动 argmax 或 argmin。

    参数
    ----------
    df : pd.DataFrame
        形状 (n_rows, n_cols)，行=时间，列=品种。
    window : int
        滚动窗口大小（bar 数），必须 >= 2。
    op : {'argmax', 'argmin'}
        取最大值或最小值的位置。
    normalize : bool
        True 时返回值归一化到 [0, 1]，False 时返回整数索引 [0, window-1]。

    返回
    -------
    pd.DataFrame
        与 df 同形状，前 window-1 行为 NaN。
    """
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")

    n_rows = len(df)
    if n_rows < window:
        # 行数不足，返回全 NaN（前 window-1 行不满，也不够产生任何一个有效窗口）
        return pd.DataFrame(np.full((n_rows, df.shape[1]), np.nan),
                            index=df.index, columns=df.columns)

    arr = df.to_numpy(dtype=float)          # (n_rows, n_cols)
    # sliding_window_view 零拷贝，NumPy 2.x 下 window 轴追加到末尾
    # shape: (n_rows - window + 1, n_cols, window)
    windows = np.lib.stride_tricks.sliding_window_view(arr, window, axis=0)

    # 在 window 轴（最后一个轴）上取最右侧最大值/最小值的位置
    # 反转 window 轴：原 [... t, t+1, ..., t+w-1] → [... t+w-1, ..., t+1, t]
    # 反转后 arg=0 对应原索引 w-1（最右侧）
    reversed_view = windows[..., ::-1]          # (n-w+1, n_cols, window)
    if op == 'argmax':
        pos = (window - 1) - np.argmax(reversed_view, axis=-1)
    elif op == 'argmin':
        pos = (window - 1) - np.argmin(reversed_view, axis=-1)
    else:
        raise ValueError(f"Invalid op: {op}")

    pos = pos.astype(float)                     # (n_rows - window + 1, n_cols)
    if normalize and window > 1:
        pos = pos / (window - 1)

    # 前 window-1 行填 NaN
    nan_rows = np.full((window - 1, df.shape[1]), np.nan)
    result = np.vstack([nan_rows, pos])
    return pd.DataFrame(result, index=df.index, columns=df.columns)


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

    # ── 可哈希（用于 set/dict 中的依赖追踪和缓存） ──

    def __hash__(self) -> int:
        return id(self)

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

    # ── 子类必须实现的接口 ──

    @property
    def dependencies(self) -> Set['FactorExpr']:
        """返回此节点依赖的上游表达式集合。叶子节点返回空集。"""
        raise NotImplementedError

    @property
    def param_deps(self) -> Set['Parameter']:
        """返回此节点依赖的参数集合。叶子节点返回空集。"""
        raise NotImplementedError

    @property
    def ordered_param_deps(self) -> List['Parameter']:
        """按表达式树深度优先遍历顺序返回依赖的参数列表（去重保留首次出现顺序）。"""
        seen: Set['Parameter'] = set()
        result: List['Parameter'] = []
        self._collect_params_ordered(seen, result)
        return result

    def _collect_params_ordered(self, seen: Set['Parameter'], result: List['Parameter']):
        """叶子节点默认无参数。子类按需覆盖。"""
        pass

    def evaluate(self, products: Sequence['Product'], freq: DataFreq,
                 source: Optional['DataSource'] = None,
                 cache: Optional[Dict['FactorExpr', pd.DataFrame]] = None) -> pd.DataFrame:
        """
        求值：对给定品种集合和数据频率，计算因子值。

        返回 DataFrame，列为 Product，索引为时间（MultiIndex）。

        参数：
            products : 品种列表
            freq     : 使用的数据频率（通常是 product.MIN1 的 freq）
            source   : 数据源。None=自动选择，指定后校验是否兼容
            cache    : 表达式→DataFrame 缓存（避免重复计算）
        """
        raise NotImplementedError

    @property
    def op_name(self) -> str:
        """表达式操作名，用于生成别名和 LaTeX。"""
        raise NotImplementedError

    def to_latex(self) -> str:
        """生成 LaTeX 数学表达式。"""
        raise NotImplementedError

    # ── 别名生成 ──

    def _get_alias(self) -> str:
        """生成唯一别名，用于 Factor 注册。"""
        raise NotImplementedError

    # ── 便利方法：时序算子 ──

    def ma(self, window: Union[int, str, pd.Timedelta]) -> 'UnaryRollingOp':
        """N 期移动平均（简单平均）。"""
        return UnaryRollingOp('ma', self, window)

    def std(self, window: Union[int, str, pd.Timedelta]) -> 'UnaryRollingOp':
        """N 期移动标准差。"""
        return UnaryRollingOp('std', self, window)

    def var(self, window: Union[int, str, pd.Timedelta]) -> 'UnaryRollingOp':
        """N 期移动方差。"""
        return UnaryRollingOp('var', self, window)

    def rolling_min(self, window: Union[int, str, pd.Timedelta]) -> 'UnaryRollingOp':
        """N 期滚动最小值。"""
        return UnaryRollingOp('min', self, window)

    def rolling_max(self, window: Union[int, str, pd.Timedelta]) -> 'UnaryRollingOp':
        """N 期滚动最大值。"""
        return UnaryRollingOp('max', self, window)

    def rolling_sum(self, window: Union[int, str, pd.Timedelta]) -> 'UnaryRollingOp':
        """N 期滚动求和。"""
        return UnaryRollingOp('sum', self, window)

    def ema(self, window: Union[int, str, pd.Timedelta]) -> 'UnaryRollingOp':
        """N 期指数移动平均（EMA, span=window）。"""
        return UnaryRollingOp('ema', self, window)

    def corr(self, other: 'FactorExpr', window: Union[int, str, pd.Timedelta]) -> 'BinaryRollingOp':
        """N 期滚动相关系数：self 与 other 的 rolling correlation。"""
        return BinaryRollingOp('corr', self, other, window)

    def skew(self, window: Union[int, str, pd.Timedelta]) -> 'UnaryRollingOp':
        """N 期滚动偏度。"""
        return UnaryRollingOp('skew', self, window)

    def argmax(self, window: Union[int, str, pd.Timedelta]) -> 'UnaryRollingOp':
        """N 期内最大值出现位置（0=最早, 1=最新），归一化到 [0,1]。"""
        return UnaryRollingOp('argmax', self, window)

    def argmin(self, window: Union[int, str, pd.Timedelta]) -> 'UnaryRollingOp':
        """N 期内最小值出现位置（0=最早, 1=最新），归一化到 [0,1]。"""
        return UnaryRollingOp('argmin', self, window)

    def shift(self, periods: Union[int, str, pd.Timedelta, 'Parameter'] = 1) -> 'ShiftOp':
        """前 N 期值：x.shift(1) 即昨天值。"""
        return ShiftOp('shift', self, periods)

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


# ═════════════════════════════════════════════════════════════════════════════
# 辅助：将标量/ndarray 转为 ConstExpr
# ═════════════════════════════════════════════════════════════════════════════

def _to_expr(value: Any) -> FactorExpr:
    """将非 FactorExpr 值包装为 ConstExpr。"""
    if isinstance(value, FactorExpr):
        return value
    return ConstExpr(value)


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

    @property
    def dependencies(self) -> Set[FactorExpr]:
        return set()

    @property
    def param_deps(self) -> Set['Parameter']:
        return set()

    def evaluate(self, products: Sequence['Product'], freq: DataFreq,
                 source: Optional['DataSource'] = None,
                 cache: Optional[Dict[FactorExpr, pd.DataFrame]] = None) -> pd.DataFrame:
        if cache is not None and self in cache:
            return cache[self]

        from tools.data.DataMeta import DataMeta

        series_dict = {}
        for p in products:
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
      - WindowParam: 值作为窗口参数传入 WindowOp
      - 任意 Parameter: 值直接作为标量参与表达式计算
    """

    def __init__(self, param: 'Parameter'):
        self.param = param

    @property
    def dependencies(self) -> Set[FactorExpr]:
        return set()

    @property
    def param_deps(self) -> Set['Parameter']:
        return {self.param}

    def _collect_params_ordered(self, seen: Set['Parameter'], result: List['Parameter']):
        if self.param not in seen:
            seen.add(self.param)
            result.append(self.param)

    def evaluate(self, products: Sequence['Product'], freq: DataFreq,
                 source: Optional['DataSource'] = None,
                 cache: Optional[Dict[FactorExpr, pd.DataFrame]] = None) -> pd.DataFrame:
        # ParamRef 不能独立求值——它需要一个宿主对象来查询注册表。
        # 求值时由 FactorFamily 在求值前将参数值替换为 ConstExpr 或 ColumnRef。
        raise RuntimeError(
            "ParamRef.evaluate() should not be called directly; "
            "parameter values must be resolved by the FactorFamily before evaluation"
        )

    def resolve(self, host: 'UniqueObject') -> Any:
        """从宿主对象的注册表中取出当前参数值。"""
        return self.param.get_value(host)

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

class ConstExpr(FactorExpr):
    """
    常量表达式 — 标量或固定值的叶子节点。

    示例：
        ConstExpr(1.0)
        ConstExpr(0.5)
    """

    def __init__(self, value: Union[int, float, np.ndarray]):
        self.value = value

    @property
    def dependencies(self) -> Set[FactorExpr]:
        return set()

    @property
    def param_deps(self) -> Set['Parameter']:
        return set()

    def evaluate(self, products: Sequence['Product'], freq: DataFreq,
                 source: Optional['DataSource'] = None,
                 cache: Optional[Dict[FactorExpr, pd.DataFrame]] = None) -> pd.DataFrame:
        # 常量不产生 DataFrame，由 CompositeExpr._apply_op 提取 value 后内联处理
        # 此处返回 self 作为特殊标记，不直接调用 evaluate
        return self  # type: ignore[return-value]

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


# ═════════════════════════════════════════════════════════════════════════════
# Layer 3: 一元算子
# ═════════════════════════════════════════════════════════════════════════════

class UnaryOp(FactorExpr):
    """
    一元算子：LOG, SIGN, ABS, NEG, NOT 等。
    """

    def __init__(self, op: str, operand: FactorExpr):
        self.op = op
        self.operand = operand

    @property
    def dependencies(self) -> Set[FactorExpr]:
        return {self.operand}

    @property
    def param_deps(self) -> Set['Parameter']:
        return self.operand.param_deps

    def _collect_params_ordered(self, seen: Set['Parameter'], result: List['Parameter']):
        self.operand._collect_params_ordered(seen, result)

    def evaluate(self, products: Sequence['Product'], freq: DataFreq,
                 source: Optional['DataSource'] = None,
                 cache: Optional[Dict[FactorExpr, pd.DataFrame]] = None) -> pd.DataFrame:
        if cache is not None and self in cache:
            return cache[self]

        x = self.operand.evaluate(products, freq, source=source, cache=cache)

        _OP_MAP = {
            'log': np.log,
            'sign': np.sign,
            'abs': np.abs,
            'neg': np.negative,
            'not': np.logical_not,
            'sqrt': np.sqrt,
        }
        func = _OP_MAP[self.op]
        result = func(x)

        if cache is not None:
            cache[self] = result
        return result

    @property
    def op_name(self) -> str:
        return self.op.upper()

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

class RollingOp(FactorExpr):
    """
    滚动窗口算子抽象基类。

    统一处理 window 参数的存储、解析、param_deps 和 _resolve_expr_params 分发。
    子类只需声明操作数（一元/二元/多元）和核心滚动运算逻辑。

    window 参数支持：
      - int: bar 数量
      - str / pd.Timedelta: 时间长度
      - Parameter (WindowParam): 运行时从 FactorFamily 注册表取值
    """

    def __init__(self, window: Union[int, str, pd.Timedelta, 'Parameter']):
        self.window = window

    # ── 子类必须实现 ──

    def _get_operands(self) -> Sequence[FactorExpr]:
        """返回此算子依赖的所有操作数表达式。"""
        raise NotImplementedError

    def _apply_rolling(self, dfs: Sequence[pd.DataFrame],
                       window: int, freq: DataFreq) -> pd.DataFrame:
        """
        核心滚动运算。

        参数：
            dfs    : 各操作数的求值结果（与 _get_operands() 顺序一致）
            window : 已解析为整数 bar 数的窗口
            freq   : 数据频率
        返回：
            DataFrame，列=Product，行=时间
        """
        raise NotImplementedError

    def _window_str(self) -> str:
        """窗口的字符串表示，用于 op_name / alias / latex。"""
        w = self.window
        if isinstance(w, int):
            return str(w)
        return str(w).replace(' ', '')

    # ── 公共接口（子类无需覆盖） ──

    @property
    def dependencies(self) -> Set[FactorExpr]:
        return set(self._get_operands())

    @property
    def param_deps(self) -> Set['Parameter']:
        from tools.parameters.Parameter import Parameter
        deps: Set['Parameter'] = set()
        for opnd in self._get_operands():
            deps |= opnd.param_deps
        if isinstance(self.window, Parameter):
            deps.add(self.window)
        return deps

    def _collect_params_ordered(self, seen: Set['Parameter'], result: List['Parameter']):
        from tools.parameters.Parameter import Parameter
        for opnd in self._get_operands():
            opnd._collect_params_ordered(seen, result)
        if isinstance(self.window, Parameter) and self.window not in seen:
            seen.add(self.window)
            result.append(self.window)

    def evaluate(self, products: Sequence['Product'], freq: DataFreq,
                 source: Optional['DataSource'] = None,
                 cache: Optional[Dict[FactorExpr, pd.DataFrame]] = None) -> pd.DataFrame:
        if cache is not None and self in cache:
            return cache[self]

        operands = self._get_operands()
        dfs = tuple(opnd.evaluate(products, freq, source=source, cache=cache)
                    for opnd in operands)
        window = _resolve_bars(self.window, freq)
        result = self._apply_rolling(dfs, window, freq)

        if cache is not None:
            cache[self] = result
        return result


# ─────────────────────────────────────────────────────────────────────────────
# 一元滚动算子（原 WindowOp）
# ─────────────────────────────────────────────────────────────────────────────

class UnaryRollingOp(RollingOp):
    """
    一元滚动窗口算子：MA(N), STD(N), MIN(N), MAX(N), SUM(N), EMA(N), SKEW(N) 等。

    对每个品种独立计算滚动窗口聚合。
    """

    def __init__(self, op: str, operand: FactorExpr,
                 window: Union[int, str, pd.Timedelta, 'Parameter']):
        super().__init__(window)
        self.op = op           # 'ma', 'std', 'var', 'min', 'max', 'sum', 'ema', 'skew', 'argmax', 'argmin'
        self.operand = operand

    def _get_operands(self) -> Sequence[FactorExpr]:
        return (self.operand,)

    def _apply_rolling(self, dfs: Sequence[pd.DataFrame],
                       window: int, freq: DataFreq) -> pd.DataFrame:
        x = dfs[0]

        # argmax/argmin 用 sliding_window_view 全向量化（比 rolling().apply 快数倍）
        if self.op in ('argmax', 'argmin') and len(x) >= window:
            return _rolling_argmaxmin(x, window, self.op)

        _OP_MAP = {
            'ma': lambda s: s.rolling(window, min_periods=max(1, window // 2)).mean(),
            'std': lambda s: s.rolling(window, min_periods=max(1, window // 2)).std(),
            'var': lambda s: s.rolling(window, min_periods=max(1, window // 2)).var(),
            'min': lambda s: s.rolling(window, min_periods=1).min(),
            'max': lambda s: s.rolling(window, min_periods=1).max(),
            'sum': lambda s: s.rolling(window, min_periods=1).sum(),
            'ema': lambda s: s.ewm(span=window, min_periods=max(1, window // 2)).mean(),
            'skew': lambda s: s.rolling(window, min_periods=max(1, window // 2)).skew(),
        }
        func = _OP_MAP[self.op]
        return x.apply(func, axis=0)

    @property
    def op_name(self) -> str:
        return f"{self.op.upper()}_{self._window_str()}"

    def to_latex(self) -> str:
        operand_latex = self.operand.to_latex()
        _LATEX_MAP = {
            'ma': f'\\text{{MA}}_{{{self.window}}}({operand_latex})',
            'std': f'\\sigma_{{{self.window}}}({operand_latex})',
            'var': f'\\sigma^2_{{{self.window}}}({operand_latex})',
            'min': f'\\min_{{{self.window}}}({operand_latex})',
            'max': f'\\max_{{{self.window}}}({operand_latex})',
            'sum': f'\\sum_{{{self.window}}}({operand_latex})',
            'ema': f'\\text{{EMA}}_{{{self.window}}}({operand_latex})',
            'skew': f'\\text{{Skew}}_{{{self.window}}}({operand_latex})',
            'argmax': f'\\text{{ArgMax}}_{{{self.window}}}({operand_latex})',
            'argmin': f'\\text{{ArgMin}}_{{{self.window}}}({operand_latex})',
        }
        return _LATEX_MAP.get(self.op, f'{self.op}_{{{self.window}}}({operand_latex})')

    def _get_alias(self) -> str:
        return f"{self.op}_{self.operand._get_alias()}_W{self._window_str()}"

    def __repr__(self) -> str:
        return f"{self.op}({self.operand}, {self.window})"


# ─────────────────────────────────────────────────────────────────────────────
# 二元滚动算子（原 CorrOp）
# ─────────────────────────────────────────────────────────────────────────────

class BinaryRollingOp(RollingOp):
    """
    二元滚动窗口算子：CORR, COV, BETA 等。

    对两个序列在相同窗口内做逐品种滚动相关/协方差/回归。
    """

    def __init__(self, op: str, left: FactorExpr, right: FactorExpr,
                 window: Union[int, str, pd.Timedelta, 'Parameter']):
        super().__init__(window)
        self.op = op            # 'corr', 'cov', 'beta', ...
        self.left = left
        self.right = right

    def _get_operands(self) -> Sequence[FactorExpr]:
        return (self.left, self.right)

    def _apply_rolling(self, dfs: Sequence[pd.DataFrame],
                       window: int, freq: DataFreq) -> pd.DataFrame:
        left_df, right_df = dfs[0], dfs[1]

        result = pd.DataFrame(index=left_df.index, columns=left_df.columns, dtype=float)
        for col in left_df.columns:
            if self.op == 'corr':
                result[col] = left_df[col].rolling(window).corr(right_df[col])
            elif self.op == 'cov':
                result[col] = left_df[col].rolling(window).cov(right_df[col])
            else:
                raise ValueError(f"Unknown binary rolling op: {self.op}")
        return result

    @property
    def op_name(self) -> str:
        return f"{self.op.upper()}_{self._window_str()}"

    def to_latex(self) -> str:
        left_latex = self.left.to_latex()
        right_latex = self.right.to_latex()
        return f'\\text{{{self.op.capitalize()}}}_{{{self.window}}}({left_latex}, {right_latex})'

    def _get_alias(self) -> str:
        return f"{self.op}_{self.left._get_alias()}_{self.right._get_alias()}_W{self._window_str()}"

    def __repr__(self) -> str:
        return f"{self.op}({self.left}, {self.right}, {self.window})"


# ─────────────────────────────────────────────────────────────────────────────
# 向后兼容别名
# ─────────────────────────────────────────────────────────────────────────────

WindowOp = UnaryRollingOp   # 旧名，保持兼容
CorrOp = BinaryRollingOp    # 旧名，保持兼容


class ShiftOp(FactorExpr):
    """
    位移算子：SHIFT(x, N) 即前 N 期的 x 值。

    periods 参数支持：
      - int: bar 数量
      - str / pd.Timedelta: 时间长度
      - Parameter (WindowParam): 运行时从 FactorFamily 注册表取值
    """

    def __init__(self, op: str, operand: FactorExpr,
                 periods: Union[int, str, pd.Timedelta, 'Parameter'] = 1):
        self.op = op           # 'ref'
        self.operand = operand
        self.periods = periods

    @property
    def dependencies(self) -> Set[FactorExpr]:
        return {self.operand}

    @property
    def param_deps(self) -> Set['Parameter']:
        from tools.parameters.Parameter import Parameter
        deps = self.operand.param_deps.copy()
        if isinstance(self.periods, Parameter):
            deps.add(self.periods)
        return deps

    def _collect_params_ordered(self, seen: Set['Parameter'], result: List['Parameter']):
        from tools.parameters.Parameter import Parameter
        self.operand._collect_params_ordered(seen, result)
        if isinstance(self.periods, Parameter) and self.periods not in seen:
            seen.add(self.periods)
            result.append(self.periods)

    def evaluate(self, products: Sequence['Product'], freq: DataFreq,
                 source: Optional['DataSource'] = None,
                 cache: Optional[Dict[FactorExpr, pd.DataFrame]] = None) -> pd.DataFrame:
        if cache is not None and self in cache:
            return cache[self]

        x = self.operand.evaluate(products, freq, source=source, cache=cache)
        periods = self._resolve_periods(self.periods, freq)
        result = x.shift(periods)

        if cache is not None:
            cache[self] = result
        return result

    @staticmethod
    def _resolve_periods(periods: Union[int, str, pd.Timedelta, 'Parameter'], freq: DataFreq) -> int:
        """将位移参数统一转换为 bar 数量。"""
        return _resolve_bars(periods, freq)

    @property
    def op_name(self) -> str:
        p = self.periods if isinstance(self.periods, int) else str(self.periods)
        return f"REF_{p}"

    def to_latex(self) -> str:
        operand_latex = self.operand.to_latex()
        # 将 period 参数名映射为可读形式
        from tools.parameters.Parameter import Parameter
        if isinstance(self.periods, Parameter):
            p_label = self.periods.alias
        else:
            p_label = str(self.periods)
        # 如果是列/参数引用且形如 "X_{t}"，替换为自然下标 "X_{t - NS}"
        if isinstance(self.operand, (ColumnRef, ParamRef)) and operand_latex.endswith('_{t}'):
            base = operand_latex[:-3]  # 去掉 "{t}"，保留 "X_"
            return base + '{t - ' + p_label + '}'
        return f"\\text{{REF}}_{{{p_label}}}({operand_latex})"

    def _get_alias(self) -> str:
        p = self.periods if isinstance(self.periods, int) else str(self.periods).replace(' ', '')
        return f"ref_{self.operand._get_alias()}_{p}"

    def __repr__(self) -> str:
        return f"ref({self.operand}, {self.periods})"


def _resolve_bars(periods: Union[int, str, pd.Timedelta, 'Parameter'], freq: DataFreq) -> int:
    """将 int / str / pd.Timedelta / Parameter 统一转换为 bar 数量。

    RollingOp、ShiftOp 共享此逻辑。
    若传入 Parameter（未解析），抛出 RuntimeError——调用者应在求值前解析。
    """
    from tools.parameters.Parameter import Parameter
    if isinstance(periods, Parameter):
        raise RuntimeError(
            f"Parameter {periods} must be resolved before evaluation"
        )
    if isinstance(periods, int):
        return periods
    if isinstance(periods, pd.Timedelta):
        td = periods
    else:
        td = pd.Timedelta(periods)
    if td.total_seconds() % freq.value.total_seconds() != 0:
        raise ValueError(f"{periods} not divisible by freq {freq.name}")
    return int(td.total_seconds() / freq.value.total_seconds())


# ═════════════════════════════════════════════════════════════════════════════
# Layer 5: 横截面算子
# ═════════════════════════════════════════════════════════════════════════════

class CrossSectionalOp(FactorExpr):
    """
    横截面算子：CS_ZSCORE, CS_RANK 等。

    在每个时间点对横截面（所有品种）进行聚合计算。
    """

    def __init__(self, op: str, operand: FactorExpr):
        self.op = op
        self.operand = operand

    @property
    def dependencies(self) -> Set[FactorExpr]:
        return {self.operand}

    @property
    def param_deps(self) -> Set['Parameter']:
        return self.operand.param_deps

    def _collect_params_ordered(self, seen: Set['Parameter'], result: List['Parameter']):
        self.operand._collect_params_ordered(seen, result)

    def evaluate(self, products: Sequence['Product'], freq: DataFreq,
                 source: Optional['DataSource'] = None,
                 cache: Optional[Dict[FactorExpr, pd.DataFrame]] = None) -> pd.DataFrame:
        if cache is not None and self in cache:
            return cache[self]

        x = self.operand.evaluate(products, freq, source=source, cache=cache)
        # x: DataFrame, index=MultiIndex(time), columns=Product

        if self.op == 'cs_zscore':
            # (x - mean) / std, across columns at each time point
            mean = x.mean(axis=1)
            std = x.std(axis=1)
            std = std.replace(0, np.nan)  # 避免除零
            result = x.sub(mean, axis=0).div(std, axis=0)
        elif self.op == 'cs_rank':
            # rank from 0 to 1
            result = x.rank(axis=1, pct=True) - 0.5  # 中心化到 [-0.5, 0.5]
        else:
            raise ValueError(f"Unknown cross-sectional op: {self.op}")

        if cache is not None:
            cache[self] = result
        return result

    @property
    def op_name(self) -> str:
        return self.op.upper()

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
# Layer 6: 复合表达式（二元运算树节点）
# ═════════════════════════════════════════════════════════════════════════════

class CompositeExpr(FactorExpr):
    """
    复合表达式 — 由两个子表达式通过二元运算符组合而成。

    表达式树内部节点。支持：
      - add, sub, mul, div（算术）
      - gt, lt, ge, le, eq, ne（比较）
      - and, or（逻辑）
      - max, min（多元聚合）
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
        """
        参数：
            op      : 操作名（'add', 'sub', 'mul', 'div', 'gt', ...）
            *operands : 子表达式（1 个用于一元 op，2 个用于二元 op）
        """
        self.op = op
        self.operands: Tuple[FactorExpr, ...] = operands

    @property
    def dependencies(self) -> Set[FactorExpr]:
        deps: Set[FactorExpr] = set()
        for opnd in self.operands:
            deps.add(opnd)
            deps.update(opnd.dependencies)
        return deps

    @property
    def param_deps(self) -> Set['Parameter']:
        pdeps: Set['Parameter'] = set()
        for opnd in self.operands:
            pdeps.update(opnd.param_deps)
        return pdeps

    def _collect_params_ordered(self, seen: Set['Parameter'], result: List['Parameter']):
        """按 operands 顺序深度优先收集参数。"""
        for opnd in self.operands:
            opnd._collect_params_ordered(seen, result)

    def evaluate(self, products: Sequence['Product'], freq: DataFreq,
                 source: Optional['DataSource'] = None,
                 cache: Optional[Dict[FactorExpr, pd.DataFrame]] = None) -> pd.DataFrame:
        if cache is not None and self in cache:
            return cache[self]

        # 递归求值所有子表达式
        values = [opnd.evaluate(products, freq, source=source, cache=cache)
                  for opnd in self.operands]

        result = self._apply_op(values)

        if cache is not None:
            cache[self] = result
        return result

    def _apply_op(self, values: List[Any]) -> pd.DataFrame:
        """根据 op 类型执行实际运算。"""
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
