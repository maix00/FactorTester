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

from tools.data.DataColumn import DataColumn
from tools.data.DataFreq import DataFreq

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.data.DataSource import DataSource
    from tools.data.DataMeta import DataMeta
    from tools.parameters.Parameter import Parameter


from .core import FactorExpr, EvaluateContext
from .operands import OperandExpr
from .leaf import ConstExpr, _to_expr

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
    })

    def __init__(self, data: FactorExpr, window: FactorExpr,
                 trunc_start: Optional[FactorExpr] = None,
                 trunc_end: Optional[FactorExpr] = None):
        self._data = data
        self._window = window
        self._trunc_start = trunc_start
        self._trunc_end = trunc_end

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

    # ── 截断 ──

    def truncate(self, start: Any, end: Any) -> 'RollingExpr':
        """返回带截断的新 RollingExpr."""
        return RollingExpr(self._data, self._window,
                           _to_expr(start), _to_expr(end))

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
                             trunc_end=self._trunc_end)
        return RollingOp(op_key, self._window, self._data,
                         trunc_start=self._trunc_start,
                         trunc_end=self._trunc_end)

    # ── 结构等价 ──

    def _structural_key(self) -> tuple:
        base = ('RollingExpr', self._data._structural_key(), self._window._structural_key())
        if self._trunc_start is not None:
            base += (self._trunc_start._structural_key(),)
        if self._trunc_end is not None:
            base += (self._trunc_end._structural_key(),)
        return base

    def resolve(self, *args, **kwargs) -> 'FactorExpr':
        resolved_data = self._data.resolve(*args, **kwargs)
        resolved_window = self._window.resolve(*args, **kwargs)
        resolved_ts = self._trunc_start.resolve(*args, **kwargs) if self._trunc_start is not None else None
        resolved_te = self._trunc_end.resolve(*args, **kwargs) if self._trunc_end is not None else None
        return RollingExpr(resolved_data, resolved_window, resolved_ts, resolved_te)

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
                 trunc_end: Optional[FactorExpr] = None):
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
        return max(0, n)

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

    def _apply_rolling(self, window: int, *dfs: pd.DataFrame,
                       freq: DataFreq,
                       trunc_start_arr: np.ndarray | None = None,
                       trunc_end_arr: np.ndarray | None = None) -> pd.DataFrame:
        # argmax/argmin：全向量化，不依赖 rolling()
        if self.op in ('rolling_argmax', 'rolling_argmin',
                       'rolling_argmax_raw', 'rolling_argmin_raw'):
            normalize = self.op in ('rolling_argmax', 'rolling_argmin')
            return _rolling_argmaxmin(dfs[0], window, self.op, normalize=normalize,
                                      trunc_start=trunc_start_arr,
                                      trunc_end=trunc_end_arr)

        # 有截断时的处理：mask 后做 rolling（仅对支持 NaN 聚合的算子）
        if trunc_start_arr is not None or trunc_end_arr is not None:
            if self.op in self._OP_MAP:
                masked = _mask_outside_trunc(dfs[0], window, trunc_start_arr, trunc_end_arr)
                func = self._OP_MAP[self.op]
                return cast(pd.DataFrame, masked.apply(func, axis=0, args=(window,)))
            raise ValueError(f"Truncation not supported for {self.op}")

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
                'rolling_argmax': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{ArgMax}}\\left({operand_latex}\\right)',
                'rolling_argmin': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{ArgMin}}\\left({operand_latex}\\right)',
                'rolling_argmax_raw': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{ArgMaxRaw}}\\left({operand_latex}\\right)',
                'rolling_argmin_raw': f'\\text{{R}}_{{{w_str}{trunc_suffix}}}\\text{{ArgMinRaw}}\\left({operand_latex}\\right)',
            }
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
        return extra

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

        # ── session-aware rolling path ──
        timeline = getattr(ctx, 'panel_timeline', None)
        use_positional = (
            timeline is not None
            and not timeline.dense_same_session
            and common
            and isinstance(common_periods, int)
            and common_periods >= 1
            and self._trunc_start is None
            and self._trunc_end is None
        )
        if use_positional:
            from .timeline import rolling_positions
            start_pos = rolling_positions(timeline, common_periods, data_vals[0])
            scheduled = timeline.scheduled_mask.reindex(
                index=data_vals[0].index, columns=data_vals[0].columns, fill_value=False,
            )
            if self.op in _POSITIONAL_AGG_OPS:
                return _positional_rolling_agg(
                    data_vals[0], common_periods, start_pos,
                    scheduled_mask=scheduled,
                    op=self.op,
                    extra=data_vals[1] if self._n_data >= 2 else None,
                )
            # fall through to standard path for ops not yet ported

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


def _rolling_argmaxmin(
    df: pd.DataFrame,
    window: int,
    op: str,
    normalize: bool = True,
    trunc_start: np.ndarray | None = None,
    trunc_end: np.ndarray | None = None,
) -> pd.DataFrame:
    """用 sliding_window_view 对 DataFrame 每列计算滚动 argmax 或 argmin。

    Parameters
    ----------
    trunc_start : (n_rows-window+1, n_cols) ndarray or None
        每行每列的截断起点偏移（0 = 窗口最左），None = 0。
    trunc_end : (n_rows-window+1, n_cols) ndarray or None
        每行每列的截断终点偏移（0 = 窗口最左），None = window-1。
    """
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")

    n_rows = len(df)
    if n_rows < window:
        return pd.DataFrame(np.full((n_rows, df.shape[1]), np.nan),
                            index=df.index, columns=df.columns)

    arr = df.to_numpy(dtype=float)
    # windows shape: (n_rows-window+1, n_cols, window)
    windows = np.lib.stride_tricks.sliding_window_view(arr, window, axis=0)

    # 如果指定了截断，mask 掉不在 [trunc_start, trunc_end] 范围内的元素
    if trunc_start is not None or trunc_end is not None:
        w_idx = np.arange(window).reshape(1, 1, window)  # (1, 1, W)
        if trunc_start is None:
            trunc_start = np.zeros(windows.shape[:2], dtype=int)
        if trunc_end is None:
            trunc_end = np.full(windows.shape[:2], window - 1, dtype=int)
        # mask: True where element is OUTSIDE [start, end]
        mask = (w_idx < trunc_start[..., np.newaxis]) | (w_idx > trunc_end[..., np.newaxis])
        windows = windows.astype(float)
        windows[mask] = np.nan

    # reversed: 最近 bar 在 index=0
    reversed_view = windows[..., ::-1]

    if op in ('rolling_argmax', 'rolling_argmax_raw'):
        # nanargmax: NaN 被忽略，全 NaN → 0（会被 nan_rows 覆盖）
        pos_matrix = np.nanargmax(reversed_view, axis=-1)
    elif op in ('rolling_argmin', 'rolling_argmin_raw'):
        pos_matrix = np.nanargmin(reversed_view, axis=-1)
    else:
        raise ValueError(f"Invalid op: {op}")

    pos = (window - 1) - pos_matrix
    pos = pos.astype(float)
    if normalize and window > 1:
        pos = pos / (window - 1)

    nan_rows = np.full((window - 1, df.shape[1]), np.nan)
    result = np.vstack([nan_rows, pos])
    return pd.DataFrame(result, index=df.index, columns=df.columns)

def _resolve_windows(window: Any, freq: Any, products: Sequence[Product]) -> Tuple[bool, int, Dict[Product, int]]:
    """将 DataFreq 类型的窗口参数转为 bar 数量（整数）。"""
    if isinstance(window, int):
        return True, window, {}
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


# ═════════════════════════════════════════════════════════════════════════════
# Session-aware positional rolling aggregation
# ═════════════════════════════════════════════════════════════════════════════

_POSITIONAL_AGG_OPS = frozenset({
    'rolling_mean', 'rolling_std', 'rolling_var', 'rolling_min',
    'rolling_max', 'rolling_sum',
    'rolling_argmax', 'rolling_argmin',
    'rolling_argmax_raw', 'rolling_argmin_raw',
    'rolling_corr', 'rolling_cov',
})


def _positional_rolling_agg(
    df: pd.DataFrame,
    window: int,
    start_positions: pd.DataFrame,
    scheduled_mask: pd.DataFrame,
    op: str,
    extra: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Compute rolling aggregation using session-aware positional windows.

    ``start_positions`` is a DataFrame where each cell contains the row position
    of the window's start bar (inclusive), or -1 to indicate fewer than *window*
    scheduled bars precede the row.

    The aggregation reads values from ``df`` between the start row and the
    current row (inclusive), keeps only scheduled slots (per ``scheduled_mask``),
    takes the last *window* values, and applies the aggregation.
    """
    n_rows, n_cols = df.shape
    arr = df.to_numpy(dtype=float)
    start_arr = start_positions.to_numpy(dtype=int)
    scheduled_arr = scheduled_mask.to_numpy(dtype=bool)
    extra_arr = extra.to_numpy(dtype=float) if extra is not None else None
    result = np.full((n_rows, n_cols), np.nan, dtype=float)

    # argmax/min needs special handling for normalize
    is_arg_op = op in ('rolling_argmax', 'rolling_argmin',
                       'rolling_argmax_raw', 'rolling_argmin_raw')
    normalize = op in ('rolling_argmax', 'rolling_argmin')

    for col_idx in range(n_cols):
        col_start = start_arr[:, col_idx]
        col_vals = arr[:, col_idx]
        col_sched = scheduled_arr[:, col_idx]
        for i in range(n_rows):
            s = col_start[i]
            if s < 0:
                continue
            # keep only scheduled positions in [s, i]
            span_mask = col_sched[s:i + 1]
            vals = col_vals[s:i + 1][span_mask]
            min_periods = max(1, window // 2)
            if len(vals) < min_periods:
                continue

            if is_arg_op:
                w = vals[-window:]
                if np.all(np.isnan(w)):
                    continue
                if op in ('rolling_argmax', 'rolling_argmax_raw'):
                    pos = np.nanargmax(w[::-1])
                else:
                    pos = np.nanargmin(w[::-1])
                raw_pos = window - 1 - pos
                if normalize and window > 1:
                    result[i, col_idx] = raw_pos / (window - 1)
                else:
                    result[i, col_idx] = float(raw_pos)
            elif op == 'rolling_mean':
                w = vals[-window:]
                if np.all(np.isnan(w)):
                    continue
                result[i, col_idx] = np.nanmean(w)
            elif op == 'rolling_std':
                w = vals[-window:]
                if np.all(np.isnan(w)):
                    continue
                result[i, col_idx] = np.nanstd(w)
            elif op == 'rolling_var':
                w = vals[-window:]
                if np.all(np.isnan(w)):
                    continue
                result[i, col_idx] = np.nanvar(w)
            elif op == 'rolling_min':
                w = vals[-window:]
                if np.all(np.isnan(w)):
                    continue
                result[i, col_idx] = np.nanmin(w)
            elif op == 'rolling_max':
                w = vals[-window:]
                if np.all(np.isnan(w)):
                    continue
                result[i, col_idx] = np.nanmax(w)
            elif op == 'rolling_sum':
                w = vals[-window:]
                result[i, col_idx] = np.nansum(w) if not np.all(np.isnan(w)) else np.nan
            elif op in ('rolling_corr', 'rolling_cov'):
                if extra_arr is None:
                    continue
                vx = vals[-window:]
                vy_full = extra_arr[s:i + 1, col_idx]
                vy = vy_full[span_mask][-window:]
                mask = ~np.isnan(vx) & ~np.isnan(vy)
                if mask.sum() < 2:
                    continue
                vxm = vx[mask]
                vym = vy[mask]
                if op == 'rolling_corr':
                    corr = np.corrcoef(vxm, vym)[0, 1]
                    result[i, col_idx] = corr
                else:
                    cov = np.cov(vxm, vym, ddof=1)[0, 1]
                    result[i, col_idx] = cov

    return pd.DataFrame(result, index=df.index, columns=df.columns)


# ═════════════════════════════════════════════════════════════════════════════
# Layer 5: 横截面算子
# ═════════════════════════════════════════════════════════════════════════════
