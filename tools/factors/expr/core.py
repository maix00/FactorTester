# =============================================================================
# tools/factors/expr/core.py
# 因子表达式系统 — 从 FactorExpr.py 拆分
# =============================================================================
from __future__ import annotations

import hashlib
import json
import math
from enum import Enum

import numpy as np
import pandas as pd
from typing import (
    TYPE_CHECKING, Any, Dict, Iterator, List, NamedTuple,
    Optional, Sequence, Set, Tuple, Union, cast
)

from tools.decorators import factor_workspace
from tools.data.types import DataFreq


def _semantic_value(value: Any) -> Any:
    """Return a deterministic JSON value for one structural-key value.

    Semantic fingerprints are persistent business identities, so they must not
    depend on Python's randomized ``hash()`` or an object's process-specific
    ``repr``.  Unknown values fail closed instead of silently producing an
    unstable identity.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return {"type": "float", "value": "nan"}
        if math.isinf(value):
            return {"type": "float", "value": "inf" if value > 0 else "-inf"}
        return value
    if isinstance(value, bytes):
        return {"type": "bytes", "hex": value.hex()}
    if isinstance(value, Enum):
        return {
            "type": "enum",
            "class": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": _semantic_value(value.value),
        }
    if isinstance(value, np.generic):
        return {
            "type": "numpy-scalar",
            "dtype": str(value.dtype),
            "value": _semantic_value(value.item()),
        }
    if isinstance(value, np.dtype):
        return {"type": "numpy-dtype", "value": str(value)}
    if isinstance(value, pd.Timedelta):
        return {"type": "timedelta", "nanoseconds": int(value.value)}
    if isinstance(value, pd.Timestamp):
        return {
            "type": "timestamp",
            "nanoseconds": int(value.value),
            "timezone": str(value.tz or ""),
        }
    if isinstance(value, tuple):
        return {"type": "tuple", "items": [_semantic_value(item) for item in value]}
    if isinstance(value, list):
        return {"type": "list", "items": [_semantic_value(item) for item in value]}
    if isinstance(value, (set, frozenset)):
        items = [_semantic_value(item) for item in value]
        return {"type": "set", "items": sorted(items, key=_semantic_json)}
    if isinstance(value, dict):
        items = [
            (_semantic_value(key), _semantic_value(item))
            for key, item in value.items()
        ]
        items.sort(key=lambda pair: _semantic_json(pair[0]))
        return {"type": "dict", "items": items}
    raise TypeError(
        "factor semantic fingerprint contains an unsupported value: "
        f"{type(value).__module__}.{type(value).__qualname__}"
    )


def _semantic_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def semantic_structural_key(value: Any) -> str:
    """Serialize a structural key for persistent identity and stable sorting."""
    return _semantic_json(_semantic_value(value))

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.data.providers import DataProviderProductTS as DataSource
    from tools.parameters.Parameter import Parameter
    from .leaf import ConstExpr, ColumnRef
    from .rolling import RollingExpr, RollingOp
    from .shift import ShiftOp
    from .cross_sectional import CrossSectionalOp
    from .timeline import PanelTimeline


# ── 求值上下文（统一 evaluate/_evaluate 签名） ──
class EvaluateContext(NamedTuple):
    """因子表达式求值所需的所有上下文参数。

    Issue #2: 将 5 种 _evaluate() 签名变体统一为 ctx: EvaluateContext。
    Run window is explicit: factor evaluation callers must pass start_dt/end_dt.
    """
    products: Sequence['Product']
    freq: DataFreq
    source: Optional['DataSource'] = None
    cache: Optional[Dict[Any, Any]] = None
    preloaded: Optional[Dict[Any, pd.DataFrame]] = None
    start_dt: Optional[Any] = None  # DataTime | None
    end_dt: Optional[Any] = None  # DataTime | None
    warmup_window: Optional[Any] = None
    run_result: Optional[Any] = None
    panel_timeline: Optional['PanelTimeline'] = None
    shared_cache_keys: Optional[frozenset[Tuple[Any, ...]]] = None



# ═════════════════════════════════════════════════════════════════════════════
# 延迟导入（避免与子模块的循环导入）
# ═════════════════════════════════════════════════════════════════════════════

_LAZY = None

def _lazy():
    global _LAZY
    if _LAZY is None:
        from .leaf import _to_expr, ConstExpr, ColumnRef, ParamRef
        from .composite import CompositeExpr
        from .rolling import RollingExpr, RollingOp
        from .shift import ShiftOp
        from .cross_sectional import CrossSectionalOp
        _LAZY = {
            '_to_expr': _to_expr,
            'ConstExpr': ConstExpr,
            'ColumnRef': ColumnRef,
            'ParamRef': ParamRef,
            'CompositeExpr': CompositeExpr,
            'RollingExpr': RollingExpr,
            'RollingOp': RollingOp,
            'ShiftOp': ShiftOp,
            'CrossSectionalOp': CrossSectionalOp,
        }
    return _LAZY


@factor_workspace
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
    _intermediate_factor: Optional[FactorExpr] = None

    @factor_workspace
    def as_intermediate(self, name: 'str | None' = None, factor: Optional['FactorExpr'] = None) -> 'FactorExpr':
        """标记此表达式节点为中间因子，evaluate 时自动创建 FactorData。

        name: 可选名称，用于后续查询（如 'FE', 'RE'）。
              None 表示匿名中间因子（仅创建 FactorData 不做命名映射）。
        """
        factor = factor or self
        self._is_intermediate = True
        self._intermediate_name = name
        self._intermediate_factor = factor
        return self

    # ── 可哈希（用于 set/dict 中的依赖追踪和缓存） ──

    def __hash__(self) -> int:
        return id(self)

    # ── 结构等价（用于 FactorData 去重 key） ──

    _SYMMETRIC_OPS = frozenset({
        'add', 'mul', 'and', 'or', 'max', 'min', 'bimax', 'bimin', 'eq', 'ne',
        'cs_spearman', 'cs_corr', 'cs_cov',
    })

    def _structural_hash(self) -> int:
        """
        递归计算表达式树的结构 hash。

        对于对称二元运算，operand 顺序无关（先 sort operands 的 hash）。
        对于非对称运算，按原始顺序计算。
        """
        return hash(self._structural_key())

    def semantic_fingerprint(self) -> str:
        """Return the stable SHA-256 identity of this formula's semantics."""
        payload = semantic_structural_key(self._structural_key()).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

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

    def supports_vectorized(self) -> bool:
        """Whether this expression can be evaluated as a whole historical table.

        Ordinary OHLCV-style FactorExpr graphs are vectorizable by default.
        Path-dependent or live-only nodes, such as future order-book/event
        fields, should override this to return False so backtest factor-mode
        selection can reject forced precomputation or choose live replay in
        auto mode.
        """
        return all(
            child.supports_vectorized()
            for child in getattr(self, "_operands", ())
            if isinstance(child, FactorExpr)
        )

    def supports_incremental(self) -> bool:
        """Whether this expression is intended to be incrementally compilable.

        Expressions default to being eligible for incremental compilation when
        their children are. This is intentionally independent from
        supports_vectorized(): live-only leaves can be non-vectorizable while
        still compiling into an incremental executor. The compiler remains the
        source of truth for detailed unsupported operators.
        """
        return all(
            child.supports_incremental()
            for child in getattr(self, "_operands", ())
            if isinstance(child, FactorExpr)
        )

    def compile_incremental(
        self,
        *,
        factor_alias: str = "factor",
        products: Sequence['Product'],
        source_freq: DataFreq | str | None = None,
    ) -> Any:
        """Compile this FactorExpr into a run-scoped incremental executor."""
        from tools.testers.backtest.engines.factors.incremental import (
            UnsupportedStreamingFactor,
            compile_incremental_factor,
        )

        if not self.supports_incremental():
            raise UnsupportedStreamingFactor(
                f"{type(self).__name__} does not support incremental execution"
            )
        return compile_incremental_factor(
            factor_alias,
            self,
            tuple(products),
            source_freq=source_freq,
        )

    def evaluate(self, *args, ctx: Optional['EvaluateContext'] = None, **kwargs) -> pd.DataFrame:
        """求值：对给定品种集合和数据频率，计算因子值。

        支持两种调用方式（Issue #2 迁移过渡期兼容）：
          - 新式: expr.evaluate(ctx=EvaluateContext(products, freq, ...))
          - 旧式: expr.evaluate(products, freq, source=..., cache=..., preloaded=...)
        """
        if ctx is None:
            ctx = EvaluateContext(
                products=cast('Sequence[Product]', args[0] if len(args) > 0 else kwargs.get('products')),
                freq=cast(DataFreq, args[1] if len(args) > 1 else kwargs.get('freq')),
                source=kwargs.get('source', None),
                cache=kwargs.get('cache', None),
                preloaded=kwargs.get('preloaded', None),
                start_dt=kwargs.get('start_dt', None),
                end_dt=kwargs.get('end_dt', None),
                warmup_window=kwargs.get('warmup_window', None),
                run_result=kwargs.get('run_result', None),
                panel_timeline=kwargs.get('panel_timeline', None),
            )
        cache = ctx.cache
        sk = self._structural_key()
        cacheable = self._is_intermediate or (
            ctx.shared_cache_keys is not None and sk in ctx.shared_cache_keys
        )
        if cacheable and cache is not None and sk in cache:
            return cache[sk]
        result = self._evaluate(ctx)
        if cacheable and cache is not None:
            cache[sk] = result
        # 全局求值进度：每次完成一个节点的实际计算后递增。
        # hook seam 归 engine 所有；server 只负责注册/消费，不反向渗入核心层。
        from tools.factors.eval_progress import bump as _bump
        _bump()
        return result
    
    def _evaluate(self, ctx: EvaluateContext) -> pd.DataFrame:
        """求值：对给定品种集合和数据频率，计算因子值。"""
        raise NotImplementedError

    @property
    def op_name(self) -> str:
        """表达式操作名，用于生成别名和 LaTeX。"""
        raise NotImplementedError

    def _to_latex(self, subst: dict | None = None) -> str:
        """生成 LaTeX 数学表达式（内部，不做 intermediate 展开）。

        subst: structural_key → symbol 映射，用于将 intermediate 替换为符号。
        """
        raise NotImplementedError

    def iter_intermediate_nodes(self) -> 'Iterator[FactorExpr]':
        """遍历表达式树，按后序（子依赖在前）产出所有 _is_intermediate 节点。

        Yields:
            node: 每个唯一的 intermediate 节点（按 structural_key 去重）。
        """
        seen: set[tuple] = set()

        def visit(node: 'FactorExpr') -> 'Iterator[FactorExpr]':
            sk = node._structural_key()
            if sk in seen:
                return
            seen.add(sk)

            for operand in getattr(node, '_operands', ()):
                yield from visit(operand)

            if node._is_intermediate:
                yield node

        yield from visit(self)

    def to_latex(self, final_name: str = 'X') -> str:
        """生成含 intermediate 分行定义的 LaTeX。

        当表达式树中存在 .as_intermediate() 标记节点时，输出:
                    \\begin{aligned}
            A_t &:= ... \\
            B_t &:= ... \\
            X_t &:= ...
                    \\end{aligned}
        其中 X_t 的定义中，已定义的 intermediate 用其符号替代。
        否则退化为 _to_latex()。
        """
        nodes = list(self.iter_intermediate_nodes())
        if not nodes:
            return self._to_latex()

        # 1) 为每个 intermediate 分配符号，生成定义行
        used: Set[str] = set()
        name_to_sk: Dict[str, tuple] = {}
        sk_to_sym: Dict[tuple, str] = {}   # structural_key → symbol
        lines: List[str] = []
        unnamed_idx = 1
        for node in nodes:
            if node._intermediate_name:
                sk = node._structural_key()
                prev_sk = name_to_sk.get(node._intermediate_name)
                if prev_sk is not None and prev_sk != sk:
                    raise ValueError(
                        f"Intermediate 名称冲突: {node._intermediate_name} 被用于不同表达式。"
                    )
                name_to_sk[node._intermediate_name] = sk
                raw = ''.join(ch if (ch.isalnum() or ch == '_') else '_' for ch in str(node._intermediate_name)).strip('_')
                base = raw or 'I'
            else:
                base = f"I{unnamed_idx}"
                unnamed_idx += 1
            sym = base
            i = 2
            while sym in used:
                sym = f"{base}_{i}"
                i += 1
            used.add(sym)
            latex_sym = f"\\mathrm{{{sym}}}"
            lines.append(f"{latex_sym}_t &:= {node._to_latex(subst=sk_to_sym)},")
            sk_to_sym[node._structural_key()] = latex_sym

        # 2) 最后一行 X_t，用符号映射递归生成
        raw = ''.join(ch if (ch.isalnum() or ch == '_') else '_' for ch in str(final_name)).strip('_')
        final_base = raw or 'X'
        final_sym = final_base
        i = 2
        while final_sym in used:
            final_sym = f"{final_base}_{i}"
            i += 1
        used.add(final_sym)

        # 递归遍历 self，遇到已映射的 intermediate 就用符号替代
        lines.append(f"{final_sym}_t &:= {self._to_latex(subst=sk_to_sym)}.")

        return "\\begin{aligned}\n" + " \\\\\n".join(lines) + "\n\\end{aligned}"

    def _get_alias(self) -> str:
        """生成唯一别名，用于 Factor 注册。"""
        raise NotImplementedError

    def _repr_head(self) -> str:
        """单个节点的展示名（不含子节点）。"""
        if hasattr(self, 'op'):
            return str(getattr(self, 'op'))
        if hasattr(self, 'column'):
            col = getattr(self, 'column')
            return f"ColumnRef[{getattr(col, 'name', col)}]"
        if hasattr(self, 'param'):
            param = getattr(self, 'param')
            return f"ParamRef[{getattr(param, 'alias', param)}]"
        if hasattr(self, 'value'):
            return f"Const[{getattr(self, 'value')!r}]"
        return type(self).__name__

    def __repr__(self) -> str:
        operands = list(getattr(self, '_operands', ()))
        head = self._repr_head()
        if not operands:
            return head
        return f"{head}({', '.join(repr(op) for op in operands)})"

    def tree_repr(self, indent: int = 2, _level: int = 0) -> str:
        """以树状格式打印表达式。"""
        branch_indent = max(indent, 2)
        horizontal = '─' * (branch_indent - 1)
        lines = [(' ' * (indent * _level)) + self._repr_head()]

        def append_children(node: 'FactorExpr', prefix: str) -> None:
            operands = list(getattr(node, '_operands', ()))
            for index, operand in enumerate(operands):
                is_last = index == len(operands) - 1
                connector = ('└' if is_last else '├') + horizontal + ' '
                if isinstance(operand, FactorExpr):
                    lines.append(f"{prefix}{connector}{operand._repr_head()}")
                    extension = (' ' if is_last else '│') + (' ' * branch_indent)
                    append_children(operand, prefix + extension)
                else:
                    lines.append(f"{prefix}{connector}{operand!r}")

        append_children(self, '')
        return '\n'.join(lines)

    @property
    def is_leaf_ref(self) -> bool:
        """是否作为依赖追踪中的叶子引用节点。"""
        ops = getattr(self, '_operands', ())
        return len(list(ops)) == 0

    @property
    def dependencies(self) -> Set['FactorExpr']:
        """返回此节点依赖的叶子表达式集合（不含自身与 ConstExpr）。"""
        deps = {
            d for d in self.get_ref_types(FactorExpr, leaf_only=True)
            if not isinstance(d, _lazy()['ConstExpr'])
        }
        deps.discard(self)
        return deps

    @property
    def param_deps(self) -> Set['Parameter']:
        """返回此节点依赖的参数集合。"""
        params: Set['Parameter'] = set()
        for ref in self.get_ref_types(_lazy()['ParamRef']):
            params.add(ref.param)
        return params

    @property
    def ordered_param_deps(self) -> List['Parameter']:
        params = list(self.param_deps)
        params.sort(key=lambda p: (type(p).__name__, p.alias))
        return params
    
    def get_ref_types(self, typ: type, leaf_only: bool = False) -> Set[Any]:
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
            ops = getattr(node, '_operands', [])
            ops_list = list(ops)
            is_leaf = node.is_leaf_ref

            if isinstance(node, typ) and (not leaf_only or is_leaf):
                result.add(node)
            for op in reversed(ops_list):
                stack.append(op)

        return result

    @property
    def column_refs(self) -> Set['ColumnRef']:
        """收集表达式树中的所有 ColumnRef 叶子节点。"""
        return self.get_ref_types(_lazy()['ColumnRef'])

    @property
    def const_refs(self) -> Set['ConstExpr']:
        """收集表达式树中的所有 ConstExpr 叶子节点"""
        return self.get_ref_types(_lazy()['ConstExpr'])

    # ── 运算符重载：自动构建 CompositeExpr ──

    @factor_workspace
    def __add__(self, other: Any) -> 'FactorExpr':
        return _lazy()['CompositeExpr']('add', self, _lazy()['_to_expr'](other))

    @factor_workspace
    def __radd__(self, other: Any) -> 'FactorExpr':
        return _lazy()['CompositeExpr']('add', _lazy()['_to_expr'](other), self)

    @factor_workspace
    def __sub__(self, other: Any) -> 'FactorExpr':
        return _lazy()['CompositeExpr']('sub', self, _lazy()['_to_expr'](other))

    @factor_workspace
    def __rsub__(self, other: Any) -> 'FactorExpr':
        return _lazy()['CompositeExpr']('sub', _lazy()['_to_expr'](other), self)

    @factor_workspace
    def __mul__(self, other: Any) -> 'FactorExpr':
        return _lazy()['CompositeExpr']('mul', self, _lazy()['_to_expr'](other))

    @factor_workspace
    def __rmul__(self, other: Any) -> 'FactorExpr':
        return _lazy()['CompositeExpr']('mul', _lazy()['_to_expr'](other), self)

    @factor_workspace
    def __truediv__(self, other: Any) -> 'FactorExpr':
        return _lazy()['CompositeExpr']('div', self, _lazy()['_to_expr'](other))

    @factor_workspace
    def __rtruediv__(self, other: Any) -> 'FactorExpr':
        return _lazy()['CompositeExpr']('div', _lazy()['_to_expr'](other), self)

    @factor_workspace
    def __neg__(self) -> 'FactorExpr':
        return _lazy()['CompositeExpr']('neg', self)

    @factor_workspace
    def __pos__(self) -> 'FactorExpr':
        return self

    @factor_workspace
    def __abs__(self) -> 'FactorExpr':
        return _lazy()['CompositeExpr']('abs', self)

    @factor_workspace
    def __gt__(self, other: Any) -> 'FactorExpr':
        return _lazy()['CompositeExpr']('gt', self, _lazy()['_to_expr'](other))

    @factor_workspace
    def __lt__(self, other: Any) -> 'FactorExpr':
        return _lazy()['CompositeExpr']('lt', self, _lazy()['_to_expr'](other))

    @factor_workspace
    def __ge__(self, other: Any) -> 'FactorExpr':
        return _lazy()['CompositeExpr']('ge', self, _lazy()['_to_expr'](other))

    @factor_workspace
    def __le__(self, other: Any) -> 'FactorExpr':
        return _lazy()['CompositeExpr']('le', self, _lazy()['_to_expr'](other))

    @factor_workspace
    def __eq__(self, other: Any) -> 'FactorExpr':  # type: ignore[override]
        return _lazy()['CompositeExpr']('eq', self, _lazy()['_to_expr'](other))

    @factor_workspace
    def __ne__(self, other: Any) -> 'FactorExpr':  # type: ignore[override]
        return _lazy()['CompositeExpr']('ne', self, _lazy()['_to_expr'](other))

    @factor_workspace
    def __and__(self, other: Any) -> 'FactorExpr':
        return _lazy()['CompositeExpr']('and', self, _lazy()['_to_expr'](other))

    @factor_workspace
    def __or__(self, other: Any) -> 'FactorExpr':
        return _lazy()['CompositeExpr']('or', self, _lazy()['_to_expr'](other))

    @factor_workspace
    def __invert__(self) -> 'FactorExpr':
        return _lazy()['CompositeExpr']('not', self)

    @factor_workspace
    def __pow__(self, other: Any) -> 'FactorExpr':
        """幂运算：self ** other。"""
        return _lazy()['CompositeExpr']('pow', self, _lazy()['_to_expr'](other))

    @factor_workspace
    def max(self, other: Any) -> 'FactorExpr':
        """逐元素最大值：max(self, other)。"""
        return _lazy()['CompositeExpr']('bimax', self, _lazy()['_to_expr'](other))

    @factor_workspace
    def min(self, other: Any) -> 'FactorExpr':
        """逐元素最小值：min(self, other)。"""
        return _lazy()['CompositeExpr']('bimin', self, _lazy()['_to_expr'](other))

    # ── 便利方法：时序算子 ──

    @factor_workspace
    def rolling_mean(self, window: Union[int, str, pd.Timedelta, 'FactorExpr', 'Parameter']) -> 'RollingOp':
        """N 期移动平均（简单平均）。"""
        return _lazy()['RollingOp']('rolling_mean', _lazy()['_to_expr'](window), self)

    @factor_workspace
    def rolling(self, window: Union[int, str, pd.Timedelta, 'FactorExpr', 'Parameter']) -> 'RollingExpr':
        """创建滚动窗口，支持 .truncate() + .mean()/.argmax_raw() 等逐步构建。

        示例：
            CLOSE.rolling(240).truncate(0, 8).argmin_raw()
        """
        return _lazy()['RollingExpr'](self, _lazy()['_to_expr'](window))

    @factor_workspace
    def rolling_std(self, window: Union[int, str, pd.Timedelta, 'FactorExpr', 'Parameter']) -> 'RollingOp':
        """N 期移动标准差。"""
        return _lazy()['RollingOp']('rolling_std', _lazy()['_to_expr'](window), self)

    @factor_workspace
    def rolling_var(self, window: Union[int, str, pd.Timedelta, 'FactorExpr', 'Parameter']) -> 'RollingOp':
        """N 期移动方差。"""
        return _lazy()['RollingOp']('rolling_var', _lazy()['_to_expr'](window), self)

    @factor_workspace
    def rolling_min(self, window: Union[int, str, pd.Timedelta, 'FactorExpr', 'Parameter']) -> 'RollingOp':
        """N 期滚动最小值。"""
        return _lazy()['RollingOp']('rolling_min', _lazy()['_to_expr'](window), self)

    @factor_workspace
    def rolling_max(self, window: Union[int, str, pd.Timedelta, 'FactorExpr', 'Parameter']) -> 'RollingOp':
        """N 期滚动最大值。"""
        return _lazy()['RollingOp']('rolling_max', _lazy()['_to_expr'](window), self)

    @factor_workspace
    def rolling_sum(self, window: Union[int, str, pd.Timedelta, 'FactorExpr', 'Parameter']) -> 'RollingOp':
        """N 期滚动求和。"""
        return _lazy()['RollingOp']('rolling_sum', _lazy()['_to_expr'](window), self)

    @factor_workspace
    def rolling_ema(self, window: Union[int, str, pd.Timedelta, 'FactorExpr', 'Parameter']) -> 'RollingOp':
        """N 期指数移动平均（EMA, span=window）。"""
        return _lazy()['RollingOp']('rolling_ema', _lazy()['_to_expr'](window), self)

    @factor_workspace
    def rolling_corr(self, other: 'FactorExpr', window: Union[int, str, pd.Timedelta, 'FactorExpr', 'Parameter']) -> 'RollingOp':
        """N 期滚动相关系数：self 与 other 的 rolling correlation。"""
        return _lazy()['RollingOp']('rolling_corr', _lazy()['_to_expr'](window), self, other)

    @factor_workspace
    def rolling_skew(self, window: Union[int, str, pd.Timedelta, 'FactorExpr', 'Parameter']) -> 'RollingOp':
        """N 期滚动偏度。"""
        return _lazy()['RollingOp']('rolling_skew', _lazy()['_to_expr'](window), self)

    @factor_workspace
    def rolling_median(
        self,
        window: Union[int, str, pd.Timedelta, 'FactorExpr', 'Parameter'],
    ) -> 'RollingOp':
        """N 期滚动中位数。"""
        return _lazy()['RollingOp']('rolling_median', _lazy()['_to_expr'](window), self)

    @factor_workspace
    def rolling_quantile(
        self,
        q: Any,
        window: Union[int, str, pd.Timedelta, 'FactorExpr', 'Parameter'],
    ) -> 'RollingOp':
        """N 期滚动 q 分位数，q 必须位于 [0, 1]。"""
        if isinstance(q, (int, float)) and not 0.0 <= float(q) <= 1.0:
            raise ValueError("rolling quantile q must be between 0 and 1")
        return _lazy()['RollingOp'](
            'rolling_quantile', _lazy()['_to_expr'](window),
            self, _lazy()['_to_expr'](q),
        )

    @factor_workspace
    def rolling_mad(
        self,
        window: Union[int, str, pd.Timedelta, 'FactorExpr', 'Parameter'],
    ) -> 'RollingOp':
        """N 期未缩放中位绝对偏差。"""
        return _lazy()['RollingOp']('rolling_mad', _lazy()['_to_expr'](window), self)

    @factor_workspace
    def rolling_linreg_slope(
        self,
        window: Union[int, str, pd.Timedelta, 'FactorExpr', 'Parameter'],
    ) -> 'RollingOp':
        """带截距的滚动线性时间趋势斜率。"""
        return _lazy()['RollingOp']('rolling_linreg_slope', _lazy()['_to_expr'](window), self)

    @factor_workspace
    def rolling_linreg_r2(
        self,
        window: Union[int, str, pd.Timedelta, 'FactorExpr', 'Parameter'],
    ) -> 'RollingOp':
        """带截距的滚动线性时间趋势 R²。"""
        return _lazy()['RollingOp']('rolling_linreg_r2', _lazy()['_to_expr'](window), self)

    @factor_workspace
    def rolling_linreg_tstat(
        self,
        window: Union[int, str, pd.Timedelta, 'FactorExpr', 'Parameter'],
    ) -> 'RollingOp':
        """滚动线性时间趋势斜率的 t 统计量。"""
        return _lazy()['RollingOp']('rolling_linreg_tstat', _lazy()['_to_expr'](window), self)

    @factor_workspace
    def rolling_linreg_resid_std(
        self,
        window: Union[int, str, pd.Timedelta, 'FactorExpr', 'Parameter'],
    ) -> 'RollingOp':
        """滚动线性时间趋势回归的残差标准差。"""
        return _lazy()['RollingOp']('rolling_linreg_resid_std', _lazy()['_to_expr'](window), self)

    @factor_workspace
    def rolling_argmax(self, window: Union[int, str, pd.Timedelta, 'FactorExpr', 'Parameter']) -> 'RollingOp':
        """N 期内最大值出现位置（0=最早, 1=最新），归一化到 [0,1]。"""
        return _lazy()['RollingOp']('rolling_argmax', _lazy()['_to_expr'](window), self)

    @factor_workspace
    def rolling_argmin(self, window: Union[int, str, pd.Timedelta, 'FactorExpr', 'Parameter']) -> 'RollingOp':
        """N 期内最小值出现位置（0=最早, 1=最新），归一化到 [0,1]。"""
        return _lazy()['RollingOp']('rolling_argmin', _lazy()['_to_expr'](window), self)

    @factor_workspace
    def bar_distance(
        self,
        condition: Any,
        *,
        scope: Any,
        select: str = "nearest",
        default: Any = np.nan,
    ) -> 'FactorExpr':
        """Distance to a matching historical value; nearest is the default."""
        from .bar_search import bar_distance

        return bar_distance(
            self,
            condition,
            scope=scope,
            select=select,
            default=default,
        )

    @factor_workspace
    def shift(self, periods: Union[int, str, pd.Timedelta, 'Parameter', 'FactorExpr'] = 1) -> 'ShiftOp':
        """前 N 期值：x.shift(1) 即昨天值。"""
        return _lazy()['ShiftOp']('shift', periods, self)

    @factor_workspace
    def delta(self, period: Union[int, str, pd.Timedelta, 'Parameter'] = 1) -> 'FactorExpr':
        """N 期变化量：self - self.shift(N)。"""
        return self - self.shift(period)

    @factor_workspace
    def log(self) -> 'FactorExpr':
        """自然对数。"""
        return _lazy()['CompositeExpr']('log', self)

    @factor_workspace
    def sign(self) -> 'FactorExpr':
        """符号函数：+1, -1, 0。"""
        return _lazy()['CompositeExpr']('sign', self)

    @factor_workspace
    def abs(self) -> 'FactorExpr':
        """绝对值。"""
        return _lazy()['CompositeExpr']('abs', self)

    @factor_workspace
    def sqrt(self) -> 'FactorExpr':
        """平方根。"""
        return _lazy()['CompositeExpr']('sqrt', self)

    @factor_workspace
    def tanh(self) -> 'FactorExpr':
        """逐元素双曲正切，将有限输入平滑压缩到 (-1, 1)。"""
        return _lazy()['CompositeExpr']('tanh', self)

    @factor_workspace
    def where(self, condition: Any, other: Any = np.nan) -> 'FactorExpr':
        """按条件选择当前表达式，否则选择 ``other``。"""
        from .conditional import where

        return where(condition, self, other)

    @factor_workspace
    def neg(self) -> 'FactorExpr':
        """取负。"""
        return _lazy()['CompositeExpr']('neg', self)

    # ── 便利方法：横截面算子 ──

    @factor_workspace
    def cs_zscore(self) -> 'CrossSectionalOp':
        """横截面 z-score 标准化（逐时间点）。"""
        return _lazy()['CrossSectionalOp']('cs_zscore', self)

    @factor_workspace
    def cs_rank(self, mask: Any = None) -> 'CrossSectionalOp':
        """横截面百分位排名（从小到大，输出约为 -0.5~0.5）。

        ``mask`` 给定时，仅在 True 的产品池内计算百分位；掩码外与原始值缺失
        的产品返回 ``NaN``。省略 ``mask`` 时保持历史全横截面语义。
        """
        if mask is None:
            return _lazy()['CrossSectionalOp']('cs_rank', self)
        return _lazy()['CrossSectionalOp'](
            'cs_rank_masked', self, _lazy()['_to_expr'](mask),
        )

    @factor_workspace
    def cs_ordinal_rank(self, mask: Any = None, *, ascending: bool = True) -> 'CrossSectionalOp':
        """掩码内的确定性横截面整数排名。

        输出从 1 开始；``ascending=True`` 时最小值为 1，反之最大值为 1。
        掩码外或原始值缺失的产品返回 ``NaN``。同分按稳定产品键打破，因而每个
        可用产品都有唯一名次，适合精确 top-k / bottom-k 筛选。
        """
        mask_expr = _lazy()['_to_expr'](True if mask is None else mask)
        op = 'cs_ordinal_rank_asc' if ascending else 'cs_ordinal_rank_desc'
        return _lazy()['CrossSectionalOp'](op, self, mask_expr)

    @factor_workspace
    def _cs_group(self, op: str, category: Any, mask: Any = None) -> 'CrossSectionalOp':
        from tools.products.categories.Category import Category
        if not isinstance(category, Category):
            raise TypeError(f"{op} requires a Category")
        return _lazy()['CrossSectionalOp'](
            op, self, _lazy()['_to_expr'](True if mask is None else mask), category=category,
        )

    @factor_workspace
    def cs_group_rank(self, category: Any, mask: Any = None) -> 'CrossSectionalOp':
        """Rank each Category label independently, then restore product order."""
        return self._cs_group('cs_group_rank', category, mask)

    @factor_workspace
    def cs_group_zscore(self, category: Any, mask: Any = None) -> 'CrossSectionalOp':
        """Z-score each Category label independently."""
        return self._cs_group('cs_group_zscore', category, mask)

    @factor_workspace
    def cs_group_demean(self, category: Any, mask: Any = None) -> 'CrossSectionalOp':
        """Subtract each product's Category-label cross-sectional mean."""
        return self._cs_group('cs_group_demean', category, mask)

    @factor_workspace
    def cs_residualize(self, *exposures: 'FactorExpr', mask: Any = None) -> 'CrossSectionalOp':
        """Return residuals from per-timestamp OLS with an intercept."""
        if not exposures:
            raise ValueError("cs_residualize requires at least one exposure")
        operands = [self, *(_lazy()['_to_expr'](item) for item in exposures), _lazy()['_to_expr'](True if mask is None else mask)]
        return _lazy()['CrossSectionalOp']('cs_residualize', *operands, exposure_count=len(exposures))

    @factor_workspace
    def cs_spearman(self, other: 'FactorExpr') -> 'CrossSectionalOp':
        """截面 Spearman 秩相关系数：self 与 other 逐时间点计算。"""
        return _lazy()['CrossSectionalOp']('cs_spearman', self, other)

    @factor_workspace
    def cs_corr(self, other: 'FactorExpr') -> 'CrossSectionalOp':
        """截面 Pearson 相关系数：self 与 other 逐时间点计算。"""
        return _lazy()['CrossSectionalOp']('cs_corr', self, other)


# ═════════════════════════════════════════════════════════════════════════════
# Layer 1.5: 多元算子基类
# ═════════════════════════════════════════════════════════════════════════════
