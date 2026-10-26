"""Same-input benchmark: 1m sine bars, window 480, one mean output."""

import statistics
import time

import numpy as np
import pandas as pd

from alpha.factor import ColumnRef, EvalContext


def main(n: int = 1_000_000, window: int = 480, repeats: int = 5) -> None:
    values = np.sin(np.arange(n, dtype=float))
    index = pd.date_range("2026-01-05", periods=n, freq="min")
    frame = pd.DataFrame({"CLOSE": values}, index=index)
    ctx = EvalContext(products=("A",), preloaded={"A": frame})
    expression = ColumnRef("CLOSE").rolling(window).mean()
    expression.evaluate(ctx)
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        expression.evaluate(ctx)
        samples.append(time.perf_counter() - started)
    print(f"batch_1m_median={statistics.median(samples):.6f}s samples={samples}")


if __name__ == "__main__":
    main()
