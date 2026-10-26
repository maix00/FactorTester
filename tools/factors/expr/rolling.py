# =============================================================================
# tools/factors/expr/rolling.py
# 因子表达式系统 — 从 FactorExpr.py 拆分
# =============================================================================
from __future__ import annotations

import numpy as np
import pandas as pd
import threading
from typing import (
    TYPE_CHECKING, Any, Callable, Dict, Iterator, List, NamedTuple,
    Optional, Sequence, Set, Tuple, Union, cast
)

from tools.data.types import DataColumn
from tools.data.types import DataFreq

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.data.providers import DataProviderProductTS as DataSource
    from tools.data.views.ProductDataView import ProductDataView
    from tools.parameters.Parameter import Parameter


from .core import FactorExpr, EvaluateContext
from .operands import OperandExpr
from .leaf import ConstExpr, _to_expr
from .rolling_arg_extrema import rolling_argmaxmin as _rolling_argmaxmin
from .rolling_statistics import ROLLING_STATISTICS, apply_rolling_statistic
from .window_semantics import DEFAULT_MIN_PERIODS, DEFAULT_NAN_POLICY, NanPolicy, default_min_periods

class RollingExpr(FactorExpr):
    """
    惰性滚动窗口节点 — 持有 data + window + 可选截断参数。

    不直接求值，而是通过 .mean() / .std() / .argmax() 等方法产生 RollingOp。

    Expression tree 角色：FactorExpr 子类，参与依赖追踪和序列化。

    operands = (data, window, [trunc_start, trunc_end])
    """

    _AGG_OPS = frozenset({
        'mean', 'std', 'var', 'min', 'max', 'sum', 'ema', 'skew',
        'corr', 'cov', 'argmax', 'argmin', 'argmax_raw', 'argmin_raw',
        'median', 'quantile', 'mad',
        'linreg_slope', 'linreg_r2', 'linreg_tstat', 'linreg_resid_std',
    })

    def __init__(self, data: FactorExpr, window: FactorExpr,
                 trunc_start: Optional[FactorExpr] = None,
                 trunc_end: Optional[FactorExpr] = None,
                 min_periods: int | None = DEFAULT_MIN_PERIODS,
                 nan_policy: NanPolicy = DEFAULT_NAN_POLICY):
        self._data = data
        self._window = window
        self._trunc_start = trunc_start
        self._trunc_end = trunc_end
        self._min_periods = _to_expr(min_periods) if min_periods is not None else None
        self._nan_policy = nan_policy

    @property
    def _operands(self) -> Sequence[FactorExpr]:
        ops = [self._data, self._window]
        if self._trunc_start is not None:
            ops.append(self._trunc_start)
        if self._trunc_end is not None:
            ops.append(self._trunc_end)
        return tuple(ops)

    @property
    def is_leaf_ref(self) -> bool:
        return False

    @property
    def op_name(self) -> str:
        return 'rolling'

    @property
    def bars(self) -> 'WindowBarsExpr':
        """将窗口长度解析为可参与截断边界运算的 bar 数表达式。"""
        return WindowBarsExpr(self._window)

    def semantics(self, *, min_periods: int | None = DEFAULT_MIN_PERIODS,
                  nan_policy: NanPolicy = DEFAULT_NAN_POLICY) -> 'RollingExpr':
        """Return a rolling expression with explicit window semantics."""
        return RollingExpr(self._data, self._window, self._trunc_start,
                           self._trunc_end, min_periods, nan_policy)

    # ── 截断 ──

    def truncate(self, start: Any, end: Any) -> 'RollingExpr':
        """返回带截断的新 RollingExpr."""
        return RollingExpr(self._data, self._window,
                           _to_expr(start), _to_expr(end),
                           self._min_periods, self._nan_policy)

    # ── 聚合方法 → RollingOp ──

    def mean(self) -> 'RollingOp':
        return self._make_rolling_op('mean')

    def std(self) -> 'RollingOp':
        return self._make_rolling_op('std')

    def var(self) -> 'RollingOp':
        return self._make_rolling_op('var')

    def min(self) -> 'RollingOp':
        return self._make_rolling_op('min')

    def max(self) -> 'RollingOp':
        return self._make_rolling_op('max')

    def sum(self) -> 'RollingOp':
        return self._make_rolling_op('sum')

    def ema(self) -> 'RollingOp':
        return self._make_rolling_op('ema')

    def skew(self) -> 'RollingOp':
        return self._make_rolling_op('skew')

    def median(self) -> 'RollingOp':
        return self._make_rolling_op('median')

    def quantile(self, q: Any) -> 'RollingOp':
        if isinstance(q, (int, float)) and not 0.0 <= float(q) <= 1.0:
            raise ValueError("rolling quantile q must be between 0 and 1")
        return self._make_rolling_op('quantile', q)

    def mad(self) -> 'RollingOp':
        return self._make_rolling_op('mad')

    def linreg_slope(self) -> 'RollingOp':
        return self._make_rolling_op('linreg_slope')

    def linreg_r2(self) -> 'RollingOp':
        return self._make_rolling_op('linreg_r2')

    def linreg_tstat(self) -> 'RollingOp':
        return self._make_rolling_op('linreg_tstat')

    def linreg_resid_std(self) -> 'RollingOp':
        return self._make_rolling_op('linreg_resid_std')

    def argmax(self) -> 'RollingOp':
        return self._make_rolling_op('argmax')

    def argmin(self) -> 'RollingOp':
        return self._make_rolling_op('argmin')

    def argmax_raw(self) -> 'RollingOp':
        return self._make_rolling_op('argmax_raw')

    def argmin_raw(self) -> 'RollingOp':
        return self._make_rolling_op('argmin_raw')

    def corr(self, other: Any) -> 'RollingOp':
        return self._make_rolling_op('corr', other)

    def cov(self, other: Any) -> 'RollingOp':
        return self._make_rolling_op('cov', other)

    def _make_rolling_op(self, agg: str, extra: Any = None) -> 'RollingOp':
        # 向前兼容：保留 'rolling_mean' 等 op 名用于 serialization/key
        op_key = f'rolling_{agg}'
        if extra is not None:
            return RollingOp(op_key, self._window, self._data, _to_expr(extra),
                             trunc_start=self._trunc_start,
                             trunc_end=self._trunc_end,
                             min_periods=self._min_periods,
                             nan_policy=self._nan_policy)
        return RollingOp(op_key, self._window, self._data,
                         trunc_start=self._trunc_start,
                         trunc_end=self._trunc_end,
                         min_periods=self._min_periods,
                         nan_policy=self._nan_policy)

    # ── 结构等价 ──

    def _structural_key(self) -> tuple:
        base = ('RollingExpr', self._data._structural_key(), self._window._structural_key())
        if self._trunc_start is not None:
            base += (self._trunc_start._structural_key(),)
        if self._trunc_end is not None:
            base += (self._trunc_end._structural_key(),)
        mp = (self._min_periods._structural_key()
              if isinstance(self._min_periods, FactorExpr) else self._min_periods)
        return base + (mp, self._nan_policy.value)

    def resolve(self, *args, **kwargs) -> 'FactorExpr':
        resolved_data = self._data.resolve(*args, **kwargs)
        resolved_window = self._window.resolve(*args, **kwargs)
        resolved_ts = self._trunc_start.resolve(*args, **kwargs) if self._trunc_start is not None else None
        resolved_te = self._trunc_end.resolve(*args, **kwargs) if self._trunc_end is not None else None
        resolved_mp = (self._min_periods.resolve(*args, **kwargs)
                       if isinstance(self._min_periods, FactorExpr) else self._min_periods)
        return RollingExpr(resolved_data, resolved_window, resolved_ts, resolved_te,
                           resolved_mp, self._nan_policy)

    def _evaluate(self, ctx: EvaluateContext) -> pd.DataFrame:
        # RollingExpr 本身不求值——聚合由 RollingOp 完成
        raise RuntimeError("RollingExpr should not be evaluated directly; use .mean()/.std() etc.")

    @property
    def dependencies(self) -> Set[FactorExpr]:
        deps: Set[FactorExpr] = set()
        deps.update(self._data.dependencies)
        deps.update(self._window.dependencies)
        if self._trunc_start is not None:
            deps.update(self._trunc_start.dependencies)
        if self._trunc_end is not None:
            deps.update(self._trunc_end.dependencies)
        if isinstance(self._min_periods, FactorExpr):
            deps.update(self._min_periods.dependencies)
        return deps

    def get_ref_types(self, typ: type, leaf_only: bool = False) -> Set[Any]:
        result: Set[Any] = set()
        if isinstance(self._data, typ) and (not leaf_only or self._data.is_leaf_ref):
            result.add(self._data)
        result.update(self._data.get_ref_types(typ, leaf_only))
        result.update(self._window.get_ref_types(typ, leaf_only))
        if self._trunc_start is not None:
            result.update(self._trunc_start.get_ref_types(typ, leaf_only))
        if self._trunc_end is not None:
            result.update(self._trunc_end.get_ref_types(typ, leaf_only))
        if isinstance(self._min_periods, FactorExpr):
            result.update(self._min_periods.get_ref_types(typ, leaf_only))
        return result

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        w_str = self._window._to_latex(subst) if isinstance(self._window, FactorExpr) else str(self._window)
        if self._trunc_start is not None and self._trunc_end is not None:
            ts_str = self._trunc_start._to_latex(subst) if isinstance(self._trunc_start, FactorExpr) else str(self._trunc_start)
            te_str = self._trunc_end._to_latex(subst) if isinstance(self._trunc_end, FactorExpr) else str(self._trunc_end)
            return f'\\mathrm{{R}}_{{{w_str},\\mathrm{{trunc}}({ts_str},{te_str})}}'
        return f'\\mathrm{{R}}_{{{w_str}}}'

    def _get_alias(self) -> str:
        return 'rolling'


class WindowBarsExpr(FactorExpr):
    """滚动窗口在当前数据频率下对应的 bar 数。"""

    def __init__(self, window: FactorExpr):
        self.window = window

    @property
    def _operands(self) -> Sequence[FactorExpr]:
        return (self.window,)

    @property
    def op_name(self) -> str:
        return 'window_bars'

    def resolve(self, *args, **kwargs) -> 'WindowBarsExpr':
        return WindowBarsExpr(self.window.resolve(*args, **kwargs))

    def _evaluate(self, ctx: EvaluateContext) -> int:
        value = self.window.value if isinstance(self.window, ConstExpr) else self.window.evaluate(ctx=ctx)
        common, periods, product_periods = _resolve_windows(value, ctx.freq, ctx.products)
        if not common:
            raise ValueError(
                f".bars cannot be evaluated to a single scalar bar count: "
                f"different products have different bar counts for window {value}. "
                f"Use a window that resolves uniformly across all products, "
                f"or avoid .bars with asynchronous product panels."
            )
        return periods

    def _to_latex(self, subst: dict | None = None) -> str:
        window_latex = self.window._to_latex(subst)
        return f'\\mathrm{{Bars}}\\left({window_latex}\\right)'

    def _get_alias(self) -> str:
        return f'BARS_{self.window._get_alias()}'

    def _structural_key(self) -> tuple:
        return ('WindowBarsExpr', self.window._structural_key())


def window_bars(window: Any) -> WindowBarsExpr:
    """Return the observation count represented by ``window`` at run time.

    Keeping this conversion inside the expression graph makes formulas that
    depend on their rolling sample size structurally identifiable.  Factor
    sources must use this helper instead of opaque custom ``FactorExpr``
    subclasses whose evaluation logic is absent from the semantic key.
    """
    return WindowBarsExpr(_to_expr(window))


# ═════════════════════════════════════════════════════════════════════════════
# RollingOp — 滚动聚合结果节点
# ═════════════════════════════════════════════════════════════════════════════

class RollingOp(OperandExpr):
    """
    滚动窗口聚合节点 — 由 RollingExpr 的 .mean()/.std() 等方法产生。

    operands = (window, data1, data2, ..., [trunc_start, trunc_end])
    window 是第一 operand，数据 operands 紧随其后，
    可选的 trunc_start / trunc_end 在最末尾。
    """

    def __init__(self, op: str, window: FactorExpr, *data_and_trunc: FactorExpr,
                 trunc_start: Optional[FactorExpr] = None,
                 trunc_end: Optional[FactorExpr] = None,
                 min_periods: int | None = DEFAULT_MIN_PERIODS,
                 nan_policy: NanPolicy = DEFAULT_NAN_POLICY):
        # 拼出 operands: (window, *data, [trunc_start], [trunc_end])
        operands: List[FactorExpr] = [window]
        extra_start = 1
        if trunc_start is not None and trunc_end is not None:
            operands.extend(data_and_trunc[:-2] if len(data_and_trunc) >= 3 else data_and_trunc)
            operands.append(trunc_start)
            operands.append(trunc_end)
        elif trunc_start is not None or trunc_end is not None:
            # 单边截断：最后一个是 trunc
            operands.extend(data_and_trunc[:-1])
            operands.append(trunc_start or trunc_end)
        else:
            operands.extend(data_and_trunc)
        self._trunc_start = trunc_start
        self._trunc_end = trunc_end
        self.min_periods = min_periods
        self.nan_policy = nan_policy
        super().__init__(op, *operands)

    @property
    def window(self) -> 'FactorExpr':
        """第一 operand：窗口参数。"""
        return self.operands[0]

    @property
    def trunc_start(self) -> Optional[FactorExpr]:
        return self._trunc_start

    @property
    def trunc_end(self) -> Optional[FactorExpr]:
        return self._trunc_end

    @property
    def _data_start(self) -> int:
        """数据 operands 的起始索引（跳过 window）。"""
        return 1

    @property
    def _n_data(self) -> int:
        """数据 operands 的数量。"""
        n = len(self.operands) - 1  # 减去 window
        if self._trunc_start is not None:
            n -= 1
        if self._trunc_end is not None:
            n -= 1
        n = max(0, n)
        if self.op == 'rolling_quantile':
            return max(0, n - 1)
        return n

    @property
    def quantile(self) -> float | None:
        if self.op != 'rolling_quantile':
            return None
        q_expr = self.operands[self._data_start + self._n_data]
        if not isinstance(q_expr, ConstExpr):
            raise TypeError("rolling_quantile q must resolve to a scalar constant")
        q = float(q_expr.value)
        if not 0.0 <= q <= 1.0:
            raise ValueError("rolling quantile q must be between 0 and 1")
        return q

    @property
    def quantile_expr(self) -> FactorExpr | None:
        """Return unresolved q for metadata/formula rendering before parameters resolve."""
        if self.op != 'rolling_quantile':
            return None
        return self.operands[self._data_start + self._n_data]

    # ── 算子映射：op → lambda(*series_or_dfs, window) ──

    _OP_MAP = {
        'rolling_mean': lambda s, w: s.rolling(w, min_periods=max(1, w // 2)).mean(),
        'rolling_std':  lambda s, w: s.rolling(w, min_periods=max(1, w // 2)).std(),
        'rolling_var':  lambda s, w: s.rolling(w, min_periods=max(1, w // 2)).var(),
        'rolling_min':  lambda s, w: s.rolling(w, min_periods=1).min(),
        'rolling_max':  lambda s, w: s.rolling(w, min_periods=1).max(),
        'rolling_sum':  lambda s, w: s.rolling(w, min_periods=1).sum(),
        'rolling_ema':  lambda s, w: s.ewm(span=w, min_periods=max(1, w // 2)).mean(),
        'rolling_skew': lambda s, w: s.rolling(w, min_periods=max(1, w // 2)).skew(),
    }

    _RUST_OPS = {
        'rolling_mean': 'mean', 'rolling_sum': 'sum',
        'rolling_var': 'var', 'rolling_std': 'std',
        'rolling_min': 'min', 'rolling_max': 'max',
        'rolling_skew': 'skew',
        'rolling_ema': 'ema',
        'rolling_argmin': 'argmin', 'rolling_argmax': 'argmax',
        'rolling_argmin_raw': 'argmin_raw', 'rolling_argmax_raw': 'argmax_raw',
        'rolling_median': 'median', 'rolling_quantile': 'quantile',
        'rolling_rank': 'rank', 'rolling_mad': 'mad',
    }

    def _min_periods_value(self, window: int) -> int:
        value = self.min_periods
        if value is None:
            return default_min_periods(self.op, window)
        if isinstance(value, ConstExpr):
            return int(value.value)
        if hasattr(value, "param") and hasattr(value.param, "default_value"):
            return int(value.param.default_value)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("min_periods must resolve to an integer constant")
        return int(value)

    def _apply_window_semantics(self, result: pd.DataFrame, values: pd.DataFrame,
                                window: int) -> pd.DataFrame:
        """Mask the Rust aggregation according to explicit window semantics."""
        min_periods = self._min_periods_value(window)
        propagate = self.nan_policy is NanPolicy.PROPAGATE
        for column in result.columns:
            raw = pd.to_numeric(values[column], errors="coerce").to_numpy(dtype=float)
            finite = np.isfinite(raw)
            counts = np.concatenate(([0], np.cumsum(finite)))
            positions = np.arange(len(raw))
            widths = np.minimum(positions + 1, window)
            valid = counts[positions + 1] - counts[np.maximum(0, positions + 1 - window)]
            mask = valid < min_periods
            if propagate:
                mask |= valid < widths
            result.loc[mask, column] = np.nan
        return result

    def _rust_rolling(self, window: int, df: pd.DataFrame,
                      quantile: float | None = None) -> pd.DataFrame | None:
        """Batch path uses the same Rust interval kernel as streaming."""
        op = self._RUST_OPS.get(self.op)
        if op is None:
            return None
        if op == 'ema':
            from alpha import interval_ema
            result = pd.DataFrame(index=df.index, columns=df.columns, dtype=float)
            for column in df.columns:
                values = pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)
                result[column] = interval_ema(
                    values, window, self._min_periods_value(window),
                    self.nan_policy is NanPolicy.PROPAGATE,
                )
            return result
        min_periods = self._min_periods_value(window)
        propagate = self.nan_policy is NanPolicy.PROPAGATE
        result = pd.DataFrame(index=df.index, columns=df.columns, dtype=float)
        try:
            from alpha import interval_rolling
        except ImportError:
            return None
        for column in df.columns:
            values = pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)
            ordinals = np.arange(len(values), dtype=np.uint64)
            starts = np.maximum(
                0, ordinals.astype(np.int64) - window + 1,
            ).astype(np.uint64)
            result[column] = interval_rolling(
                values, starts, ordinals, op, quantile, window,
            )
        return self._apply_window_semantics(result, df, window)

    def _rust_rolling_pair(self, window: int, left: pd.DataFrame,
                           right: pd.DataFrame) -> pd.DataFrame | None:
        op = {'rolling_cov': 'cov', 'rolling_corr': 'corr'}.get(self.op)
        if op is None:
            return None
        try:
            from alpha import interval_rolling_pair
        except ImportError:
            return None
        result = pd.DataFrame(index=left.index, columns=left.columns, dtype=float)
        for column in left.columns:
            x = pd.to_numeric(left[column], errors="coerce").to_numpy(dtype=float)
            y = pd.to_numeric(right[column], errors="coerce").to_numpy(dtype=float)
            ordinals = np.arange(len(x), dtype=np.uint64)
            starts = np.maximum(
                0, ordinals.astype(np.int64) - window + 1,
            ).astype(np.uint64)
            result[column] = interval_rolling_pair(
                x, y, starts, ordinals, op == 'corr', window,
            )
        return self._apply_window_semantics(result, left, window)

    def _apply_rolling(self, window: int, *dfs: pd.DataFrame,
                       freq: DataFreq,
                       trunc_start_arr: np.ndarray | None = None,
                       trunc_end_arr: np.ndarray | None = None) -> pd.DataFrame:
        if trunc_start_arr is None and trunc_end_arr is None and len(dfs) == 2:
            rust_pair = self._rust_rolling_pair(window, dfs[0], dfs[1])
            if rust_pair is not None:
                return rust_pair
        if trunc_start_arr is None and trunc_end_arr is None and len(dfs) == 1:
            quantile = None
            if self.op == 'rolling_quantile':
                q = self.quantile
                quantile = float(q) if isinstance(q, (int, float)) else None
            rust = self._rust_rolling(window, dfs[0], quantile)
            if rust is not None:
                return rust
        # argmax/argmin：全向量化，不依赖 rolling()
        if self.op in ('rolling_argmax', 'rolling_argmin',
                       'rolling_argmax_raw', 'rolling_argmin_raw'):
            normalize = self.op in ('rolling_argmax', 'rolling_argmin')
            return _rolling_argmaxmin(dfs[0], window, self.op, normalize=normalize,
                                      trunc_start=trunc_start_arr,
                                      trunc_end=trunc_end_arr)

        # 有截断时的处理：mask 后做 rolling（仅对支持 NaN 聚合的算子）
        if trunc_start_arr is not None or trunc_end_arr is not None:
            if self.op == 'rolling_skew':
                masked = _mask_outside_trunc(dfs[0], window, trunc_start_arr, trunc_end_arr)
                return apply_rolling_statistic(
                    self.op, masked, window,
                    min_periods=self.min_periods,
                    propagate_nan=self.nan_policy is NanPolicy.PROPAGATE,
                )
            if self.op in self._OP_MAP:
                masked = _mask_outside_trunc(dfs[0], window, trunc_start_arr, trunc_end_arr)
                func = self._OP_MAP[self.op]
                return cast(pd.DataFrame, masked.apply(func, axis=0, args=(window,)))
            raise ValueError(f"Truncation not supported for {self.op}")

        if self.op == 'rolling_skew' or self.op in ROLLING_STATISTICS:
            return apply_rolling_statistic(
                self.op, dfs[0], window, quantile=self.quantile,
                min_periods=self.min_periods,
                propagate_nan=self.nan_policy is NanPolicy.PROPAGATE,
            )
        if self.op in self._OP_MAP:
            func = self._OP_MAP[self.op]
            return cast(pd.DataFrame, dfs[0].apply(func, axis=0, args=(window,)))

        # 二元
        if self.op in ('rolling_corr', 'rolling_cov'):
            left_df, right_df = dfs
            result = pd.DataFrame(index=left_df.index, columns=left_df.columns, dtype=float)
            for col in left_df.columns:
                if self.op == 'rolling_corr':
                    result[col] = left_df[col].rolling(window).corr(right_df[col])
                else:
                    result[col] = left_df[col].rolling(window).cov(right_df[col])
            return result

        raise ValueError(f"Unknown rolling op: {self.op}")

    # ── 展示方法 ──

    @property
    def operand(self) -> FactorExpr:
        """数据操作数（向后兼容，一元时使用）。"""
        return self.operands[self._data_start]

    @property
    def op_name(self) -> str:
        p = self.window
        label = str(p.value) if isinstance(p, ConstExpr) else str(p)
        return f"{self.op.upper()}_{label}"

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        w_str = self.window._to_latex(subst) if isinstance(self.window, FactorExpr) else str(self.window)

        # 截断后缀
        trunc_suffix = ''
        if self._trunc_start is not None and self._trunc_end is not None:
            ts_str = self._trunc_start._to_latex(subst) if isinstance(self._trunc_start, FactorExpr) else str(self._trunc_start)
            te_str = self._trunc_end._to_latex(subst) if isinstance(self._trunc_end, FactorExpr) else str(self._trunc_end)
            trunc_suffix = f',\\mathrm{{trunc}}({ts_str},{te_str})'

        if self._n_data == 1:
            operand_latex = self.operands[self._data_start]._to_latex(subst)
            _LATEX_MAP = {
                'rolling_mean': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{Mean}}\\left({operand_latex}\\right)',
                'rolling_std': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{Std}}\\left({operand_latex}\\right)',
                'rolling_var': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{Var}}\\left({operand_latex}\\right)',
                'rolling_min': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{Min}}\\left({operand_latex}\\right)',
                'rolling_max': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{Max}}\\left({operand_latex}\\right)',
                'rolling_sum': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{Sum}}\\left({operand_latex}\\right)',
                'rolling_ema': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{EMA}}\\left({operand_latex}\\right)',
                'rolling_skew': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{Skew}}\\left({operand_latex}\\right)',
                'rolling_median': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{Median}}\\left({operand_latex}\\right)',
                'rolling_mad': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{MAD}}\\left({operand_latex}\\right)',
                'rolling_linreg_slope': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{LinRegSlope}}\\left({operand_latex}\\right)',
                'rolling_linreg_r2': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{LinRegR2}}\\left({operand_latex}\\right)',
                'rolling_linreg_tstat': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{LinRegT}}\\left({operand_latex}\\right)',
                'rolling_linreg_resid_std': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{LinRegResidStd}}\\left({operand_latex}\\right)',
                'rolling_argmax': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{ArgMax}}\\left({operand_latex}\\right)',
                'rolling_argmin': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{ArgMin}}\\left({operand_latex}\\right)',
                'rolling_argmax_raw': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{ArgMaxRaw}}\\left({operand_latex}\\right)',
                'rolling_argmin_raw': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{ArgMinRaw}}\\left({operand_latex}\\right)',
            }
            if self.op == 'rolling_quantile':
                q_expr = self.quantile_expr
                q_latex = (
                    q_expr._to_latex(subst)
                    if isinstance(q_expr, FactorExpr)
                    else str(q_expr)
                )
                return (
                    f'\\text{{R}}_{{{w_str}{trunc_suffix}}}'
                    f'\\text{{Quantile}}_{{{q_latex}}}'
                    f'\\left({operand_latex}\\right)'
                )
            return _LATEX_MAP.get(self.op, f'{self.op}_{{{w_str}}}{operand_latex}')
        else:
            left_latex = self.operands[self._data_start]._to_latex(subst)
            right_latex = self.operands[self._data_start + 1]._to_latex(subst)
            return f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{{self.op.replace("rolling_", "").capitalize()}}}\\left({left_latex}, {right_latex}\\right)'

    def _get_alias(self) -> str:
        parts = [self.op]
        for opnd in self.operands[self._data_start:]:
            parts.append(opnd._get_alias())
        p_expr = self.window
        p = str(p_expr.value) if isinstance(p_expr, ConstExpr) else str(p_expr).replace(' ', '')
        parts.append(p)
        return "_".join(parts)

    def _structural_extra(self) -> tuple:
        extra = ()
        if self._trunc_start is not None:
            extra += (self._trunc_start._structural_key(),)
        if self._trunc_end is not None:
            extra += (self._trunc_end._structural_key(),)
        mp = (self.min_periods._structural_key()
              if isinstance(self.min_periods, FactorExpr) else self.min_periods)
        return extra + (mp, self.nan_policy.value)

    def resolve(self, *args, **kwargs) -> 'FactorExpr':
        resolved = [opnd.resolve(*args, **kwargs) for opnd in self._operands]
        mp = (self.min_periods.resolve(*args, **kwargs)
              if isinstance(self.min_periods, FactorExpr) else self.min_periods)
        return type(self)(
            self.op, *resolved,
            min_periods=mp, nan_policy=self.nan_policy,
        )

    def _evaluate(self, ctx: EvaluateContext) -> pd.DataFrame:

        # 先求值数据 operands
        data_start = self._data_start
        data_end = data_start + self._n_data
        data_vals = [opnd.evaluate(ctx=ctx) for opnd in self.operands[data_start:data_end]]

        # 求值窗口
        periods_expr = self.operands[0]
        if isinstance(periods_expr, ConstExpr):
            periods_val = periods_expr.value
        else:
            periods_val = periods_expr.evaluate(ctx=ctx)
            if isinstance(periods_val, ConstExpr):
                periods_val = periods_val.value

        common, common_periods, product_periods = _resolve_windows(
            window=periods_val, freq=ctx.freq,
            products=[p for p in ctx.products if p in data_vals[0].columns])

        timeline = getattr(ctx, 'panel_timeline', None)
        use_compacted = (
            timeline is not None
            and bool(timeline.same_session) is False
            and self._trunc_start is None
            and self._trunc_end is None
        )
        if use_compacted:
            from .timeline import compact_observed, scatter_observed

            packed_values = []
            ordinals = observed = None
            for value in data_vals:
                packed, value_ordinals, value_observed = compact_observed(value, timeline)
                packed_values.append(packed)
                if ordinals is None:
                    ordinals, observed = value_ordinals, value_observed
            if common:
                packed_result = self._apply_rolling(
                    int(common_periods), *packed_values, freq=ctx.freq,
                )
            else:
                packed_result = pd.DataFrame(
                    np.nan, index=packed_values[0].index, columns=packed_values[0].columns,
                )
                for periods in set(product_periods.values()):
                    columns = [
                        product for product, value in product_periods.items()
                        if value == periods and product in packed_values[0].columns
                    ]
                    if columns:
                        packed_result[columns] = self._apply_rolling(
                            int(periods), *[value[columns] for value in packed_values],
                            freq=ctx.freq,
                        )
            return scatter_observed(packed_result, data_vals[0], ordinals, observed)
        if (
            timeline is not None
            and bool(timeline.same_session) is False
            and (self._trunc_start is not None or self._trunc_end is not None)
        ):
            raise ValueError("异步交易时段面板暂不支持动态截断滚动窗口")

        # 确定每个 product 对应的窗口大小（用于截断数组的 shape 对齐）
        if common:
            window_per_product = {p: common_periods for p in data_vals[0].columns}
        else:
            window_per_product = product_periods

        # 求值 trunc_start / trunc_end（如果有——动态截断）
        trunc_start_arr = None
        trunc_end_arr = None
        if self._trunc_start is not None and self._trunc_end is not None:
            def as_trunc_array(value: Any) -> np.ndarray:
                if isinstance(value, pd.DataFrame):
                    return value.reindex(
                        index=data_vals[0].index,
                        columns=data_vals[0].columns,
                    ).to_numpy(dtype=float)
                return np.full(data_vals[0].shape, value, dtype=float)

            ts_arr = as_trunc_array(self._trunc_start.evaluate(ctx=ctx))
            te_arr = as_trunc_array(self._trunc_end.evaluate(ctx=ctx))
            # trunc 是对窗口内的偏移截断，需要 shape=(T-W+1, P)
            # 取公共窗口最小值做 shape 截取；不同 product 按 product_periods 分流时再调整
            if common and common_periods < len(ts_arr):
                ts_arr = ts_arr[common_periods - 1:]
                te_arr = te_arr[common_periods - 1:]
            trunc_start_arr = ts_arr
            trunc_end_arr = te_arr

        if common:
            result = self._apply_rolling(common_periods, *data_vals, freq=ctx.freq,
                                         trunc_start_arr=trunc_start_arr,
                                         trunc_end_arr=trunc_end_arr)
        else:
            unique_periods = set(product_periods.values())
            periods_products_map = {
                p: [product for product, period in product_periods.items() if period == p]
                for p in unique_periods
            }
            result_parts = []
            for p, products_group in periods_products_map.items():
                part_trunc_s = trunc_start_arr[:, [list(data_vals[0].columns).index(c) for c in products_group]] if trunc_start_arr is not None else None  # noqa: E501
                part_trunc_e = trunc_end_arr[:, [list(data_vals[0].columns).index(c) for c in products_group]] if trunc_end_arr is not None else None  # noqa: E501
                result_parts.append(self._apply_rolling(
                    p, *[dv[products_group] for dv in data_vals], freq=ctx.freq,
                    trunc_start_arr=part_trunc_s,
                    trunc_end_arr=part_trunc_e))
            result = pd.concat(result_parts, axis=1)

        return result



def _mask_outside_trunc(
    df: pd.DataFrame,
    window: int,
    trunc_start: np.ndarray | None,
    trunc_end: np.ndarray | None,
) -> pd.DataFrame:
    """将每列滚动窗口内 [trunc_start, trunc_end] 之外的值设为 NaN。

    用于支持带截断的 rolling 聚合。
    """
    if trunc_start is None and trunc_end is None:
        return df

    arr = df.to_numpy(dtype=float)
    n_rows, n_cols = arr.shape
    if n_rows < window:
        return df

    # 使用 sliding_window_view 给每个窗口内 [0,W) 外的元素设 NaN
    windows = np.lib.stride_tricks.sliding_window_view(arr, window, axis=0)
    # shape: (T-W+1, P, W)

    w_idx = np.arange(window).reshape(1, 1, window)
    if trunc_start is not None:
        start_2d = trunc_start.reshape(trunc_start.shape[0], trunc_start.shape[1], 1)
        mask_start = w_idx < start_2d
        windows[mask_start] = np.nan
    if trunc_end is not None:
        end_2d = trunc_end.reshape(trunc_end.shape[0], trunc_end.shape[1], 1)
        mask_end = w_idx > end_2d
        windows[mask_end] = np.nan

    # 不等于用 NaN 去原数组，原数组对滚动位置会自动跳过
    # 但这里我们只需要原数据（rolling 会自行滑动），mask 已在 windows 上不做持久影响
    # 实际上对于 rolling().mean()，NaN 作为数据点会被跳过，所以只需把对应位置设为 NaN 在原 df
    result = df.copy()
    result_arr = result.to_numpy(dtype=float)
    if trunc_start is not None:
        for i in range(window - 1, n_rows):
            for j in range(n_cols):
                s = int(trunc_start[i - window + 1, j])
                if s > 0:
                    result_arr[i - window + 1:i - window + 1 + s, j] = np.nan
    if trunc_end is not None:
        for i in range(window - 1, n_rows):
            for j in range(n_cols):
                e = int(trunc_end[i - window + 1, j])
                if e < window - 1:
                    result_arr[i - e:i + 1, j] = np.nan

    return pd.DataFrame(result_arr, index=df.index, columns=df.columns)


def _resolve_windows(
    window: Any,
    freq: Any,
    products: Sequence[Product],
    *,
    allow_zero: bool = False,
    allow_negative: bool = False,
) -> Tuple[bool, int, Dict[Product, int]]:
    """将 DataFreq 类型的窗口参数转为 bar 数量（整数）。"""
    bar_count = _coerce_bar_count_window(window, allow_zero=allow_zero, allow_negative=allow_negative)
    if bar_count is not None:
        if freq is None:
            raise ValueError("裸数字滚动窗口需要先解析数据频率，无法在 freq=None 时解释 bar 数")
        return True, bar_count, {}
    window = DataFreq(window)
    freq = DataFreq(freq)
    days = window.days
    freq_subday_sec = freq.subday.total_seconds()
    if freq_subday_sec == 0:
        subday_periods = 0
    else:
        subday_periods = int(window.subday.total_seconds() / freq_subday_sec)
    if days == 0:
        return True, subday_periods, {}
    else:
        product_periods = {product: int(subday_periods + days * getattr(product, freq.name).day_periods) for product in products}
        if product_periods.values() and len(set(product_periods.values())) == 1:
            return True, next(iter(product_periods.values())), {}
        return False, 0, product_periods


def _coerce_bar_count_window(
    window: Any,
    *,
    allow_zero: bool = False,
    allow_negative: bool = False,
) -> int | None:
    if isinstance(window, bool):
        return None
    if isinstance(window, int):
        if (window < 0 and not allow_negative) or (window == 0 and not allow_zero):
            raise ValueError(f"滚动窗口 bar 数必须为正整数，收到 {window!r}")
        return int(window)
    if isinstance(window, str):
        text = window.strip()
        signed_text = text[1:] if text.startswith("-") else text
        if signed_text.isdigit():
            count = int(text)
            if (count < 0 and not allow_negative) or (count == 0 and not allow_zero):
                raise ValueError(f"滚动窗口 bar 数必须为正整数，收到 {window!r}")
            return count
    return None
