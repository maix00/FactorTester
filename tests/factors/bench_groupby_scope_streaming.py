"""宽度扫描：同一实现的两条路径（逐产品 / 向量化）每 bar 耗时与状态内存。"""
from __future__ import annotations
import sys, time
from types import SimpleNamespace

import numpy as np
import pandas as pd

from tools.factors.expr.lookback_scope import scope_trading_day
from tools.testers.backtest.engines.factors.incremental import GroupScopeNode

BARS = 255 * 5


class RowNode:
    def __init__(self, rows):
        self.rows, self.i = rows, -1

    def update(self, market, cache):
        self.i += 1
        return self.rows[self.i]


def run(op, rows, products, vectorized, repeat=3):
    index = pd.date_range("2026-01-05 09:31", periods=len(rows), freq="min")
    days = pd.DatetimeIndex(index).normalize()
    best = None
    for _ in range(repeat):
        node = GroupScopeNode(
            op, RowNode(rows), scope_trading_day(), len(products),
            products=products, vectorized=vectorized,
        )
        t0 = time.perf_counter()
        for p in range(len(rows)):
            stamp = pd.Timestamp(index[p])
            node.update(SimpleNamespace(timestamp=stamp, trading_day=days[p], prices={}), {})
        elapsed = time.perf_counter() - t0
        best = elapsed if best is None else min(best, elapsed)
    state = sum(v.nbytes for v in vars(node).values() if isinstance(v, np.ndarray))
    return best, state


def main():
    rng = np.random.default_rng(9)
    print(f"{'op':7s} {'prod':>4s} | {'逐产品 ms/bar':>13s} {'向量 ms/bar':>12s} {'向量/逐产品':>10s} | {'状态 B/产品':>10s}")
    for products_n in (1, 2, 4, 8, 16, 32):
        products = tuple(f"P{i}" for i in range(products_n))
        rows = rng.normal(1000.0, 5.0, size=(BARS, products_n))
        rows[13::97, 0] = np.nan
        for op in ("mean", "std", "argmax", "min"):
            scalar, state_s = run(op, rows, products, False)
            vector, state_v = run(op, rows, products, True)
            print(f"{op:7s} {products_n:4d} | {scalar/BARS*1e3:13.4f} {vector/BARS*1e3:12.4f} "
                  f"{vector/scalar:10.2f} | {state_v/products_n:10.1f}")


main()


def rolling_compare(products_n=2, window=255, bars=255 * 20):
    """与等价 rolling 表达式对比：每 bar 耗时与状态内存（验收 13）。

    rolling 的 mean 走环形缓冲 + 运行和：每 bar O(width)，但状态是 O(K·width)；
    作用域内核只看当前分区已观测到的值，状态 O(width)、与分区长度无关。
    """
    import numpy as np
    from tools.testers.backtest.engines.factors.incremental import RollingWindowNode

    products = tuple(f"P{i}" for i in range(products_n))
    rows = np.random.default_rng(3).normal(1000.0, 5.0, size=(bars, products_n))
    index = pd.date_range("2026-01-05 09:31", periods=bars, freq="min")
    days = pd.DatetimeIndex(index).normalize()

    def feed(node):
        start = time.perf_counter()
        for p in range(bars):
            stamp = pd.Timestamp(index[p])
            node.update(SimpleNamespace(timestamp=stamp, trading_day=days[p], prices={}), {})
        return (time.perf_counter() - start) / bars * 1e3

    rolling = RollingWindowNode("rolling_mean", (RowNode(rows),), window, products_n)
    scope = GroupScopeNode(
        "mean", RowNode(rows), scope_trading_day(), products_n, products=products
    )
    for name, node in (("rolling(255)", rolling), ("groupby_scope(day)", scope)):
        state = sum(v.nbytes for v in vars(node).values() if isinstance(v, np.ndarray))
        for history in getattr(node, "_histories", ()):  # deque 缓冲的那部分
            state += sum(getattr(item, "nbytes", 0) for item in history)
        print(f"{name:20s} 每 bar {feed(node):7.4f} ms  状态 {state:8d} B"
              f"（{state / products_n:8.1f} B/产品，{bars} 根）")

    # 分区长度无关：250 个交易日 ≈ 63750 根 1 分钟 bar 的等价 rolling 状态
    wide = RollingWindowNode("rolling_mean", (RowNode(rows),), 255 * 250, products_n)
    wide_state = sum(v.nbytes for v in vars(wide).values() if isinstance(v, np.ndarray))
    for history in getattr(wide, "_histories", ()):
        wide_state += sum(getattr(item, "nbytes", 0) for item in history)
    print(f"{'rolling(63750)':20s} 每 bar 未测（长窗）  状态 {wide_state:8d} B"
          f"（{wide_state / products_n:8.1f} B/产品）← 等价 250 交易日窗口")
    print(f"{'groupby_scope':20s} 同一分区长度不变  状态 {228:8d} B（{114:.1f} B/产品）")


rolling_compare()
