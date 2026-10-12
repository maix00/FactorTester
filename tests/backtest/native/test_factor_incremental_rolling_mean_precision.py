from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tools.data.types import DataColumn, DataFreq
from tools.factors.expr import ColumnRef, EvaluateContext


@pytest.mark.parametrize("operation", ["rolling_mean", "rolling_sum"])
def test_incremental_rolling_sum_kernels_do_not_accumulate_large_offset_drift(
    operation: str,
) -> None:
    base = 1.0e12
    rng = np.random.default_rng(423_22)
    values = base + rng.normal(scale=np.spacing(base) * 4.0, size=20_000)
    values[::101] = np.nan
    values[::173] = np.inf
    index = pd.date_range("2026-01-05 09:00", periods=len(values), freq="min")
    frame = pd.DataFrame(
        {DataColumn.CLOSE_ADJUSTED.name: values},
        index=index,
    )
    expression = getattr(ColumnRef(DataColumn.CLOSE_ADJUSTED), operation)(3)
    batch = expression.evaluate(
        ctx=EvaluateContext(
            products=("P",),
            freq=DataFreq.MIN1,
            cache={},
            preloaded={("P", DataFreq.MIN1.name): frame},
        )
    )

    executor = expression.compile_incremental(
        factor_alias=f"{operation}_precision",
        products=("P",),
        source_freq=DataFreq.MIN1,
    )
    live = np.empty(len(values), dtype=float)
    for position, (timestamp, value) in enumerate(zip(index, values, strict=True)):
        executor.on_bar(
            timestamp,
            {"P": {DataColumn.CLOSE_ADJUSTED.name: value}},
        )
        live[position] = executor.on_signal(timestamp)["P"]

    expected = batch["P"].to_numpy()
    max_error = np.nanmax(np.abs(live - expected))
    reference = base if operation == "rolling_mean" else 3.0 * base
    assert max_error <= 4.0 * np.spacing(reference)
