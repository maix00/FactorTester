"""batch 侧 groupby_scope 批量内核的实测（验收 13 的基准）。

改造前后（8 产品、318 交易日、1 分钟，每观测 µs）：
  mean/std/min/max ≈ 0.10–0.12 不变；median ≈ 0.27 不变；
  argmax/argmin 5.27 → 0.06（前缀扫描替代逐根循环，8 产品总耗时 3.42s → 0.04s）。
：每算子耗时与内存，随产品数变化。

用真实节奏的面板（1 分钟、255 根/交易日、318 个交易日），比较逐产品列的
Python 循环是否为瓶颈，作为「是否需要向量化改造」的判据。
"""
from __future__ import annotations

import sys
import time
import resource

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from tools.data.types import DataFreq
from tools.factors.expr import EvaluateContext
from tools.factors.expr.groupby_scope_eval import apply_grouped
from tools.factors.expr.lookback_scope import scope_bars, scope_trading_day
from tools.factors.expr.timeline import PanelTimeline

DAYS = 318
BARS_PER_DAY = 255
OPS = ("mean", "std", "min", "max", "argmax", "median")


def build(products_n: int, seed: int = 5):
    rng = np.random.default_rng(seed)
    index = pd.DatetimeIndex(
        np.concatenate(
            [
                pd.date_range(f"2024-01-{2 + d % 27:02d} 09:31", periods=BARS_PER_DAY, freq="min")
                for d in range(DAYS)
            ]
        )
    )
    products = tuple(f"P{i}" for i in range(products_n))
    values = rng.normal(1000.0, 5.0, size=(len(index), products_n))
    values[13::97, 0] = np.nan
    frame = pd.DataFrame(values, index=index, columns=products)
    timeline = PanelTimeline(
        index=index,
        products=products,
        trading_days=pd.Index(pd.DatetimeIndex(index).normalize(), name="DAY1"),
        observed_mask=frame.notna(),
        same_session=True,
    )
    ctx = EvaluateContext(
        products=products, freq=DataFreq.MIN1, cache={}, panel_timeline=timeline
    )
    return frame, ctx


def main():
    print(f"面板：{DAYS} 交易日 × {BARS_PER_DAY} 根／日，1 分钟；逐算子计时（best of 2）")
    print(f"{'products':>8s} {'op':7s} {'scope':>12s} {'秒':>8s} {'每列每根 µs':>10s}")
    for products_n in (2, 8):
        frame, ctx = build(products_n)
        rows = len(frame)
        for scope_name, scope in (("trading_day", scope_trading_day), ("bars(255)", lambda: scope_bars(255))):
            for op in OPS:
                best = None
                for _ in range(2):
                    started = time.perf_counter()
                    apply_grouped(op, scope(), frame, ctx=ctx)
                    elapsed = time.perf_counter() - started
                    best = elapsed if best is None else min(best, elapsed)
                per = best / (rows * products_n) * 1e6
                print(f"{products_n:8d} {op:7s} {scope_name:>12s} {best:8.3f} {per:10.3f}")
    peak_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # macOS 单位是字节
    print(f"峰值 RSS：{peak_bytes / 1024 ** 2:.1f} MiB")


main()
