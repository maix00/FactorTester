"""Same-input benchmark for batch and incremental alpha factor paths."""

import time

import numpy as np
import pandas as pd

from alpha.factor import ColumnRef, EvalContext


def main(n: int = 1_000_000, window: int = 480) -> None:
    values = np.random.default_rng(3).standard_normal(n)
    index = pd.date_range("2026-01-05", periods=n, freq="min")
    frame = pd.DataFrame({"CLOSE": values}, index=index)
    ctx = EvalContext(products=("A",), preloaded={"A": frame})
    expression = ColumnRef("CLOSE").rolling(window).mean()
    expression.evaluate(ctx)
    started = time.perf_counter()
    expression.evaluate(ctx)
    print(f"batch_{n}={time.perf_counter() - started:.4f}s")


if __name__ == "__main__":
    main()
