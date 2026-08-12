from __future__ import annotations

import numpy as np
import pandas as pd

from server.modules.single_factor_test.ic import _compact_ic_series


def test_compact_ic_series_drops_auxiliary_levels_and_compresses_long_roots():
    signal = pd.date_range("2024-01-01", periods=3, freq="min")
    index = pd.MultiIndex.from_arrays(
        [signal.normalize(), signal], names=["DAY1", "_SIGNAL@MIN1"],
    )
    series = pd.Series([0.1, 0.2, 0.3], index=index)
    cache = {}

    compact = _compact_ic_series(
        series,
        display_alias="factor",
        index_cache=cache,
        preserve_precision=False,
    )

    assert isinstance(compact.index, pd.DatetimeIndex)
    assert compact.index.name == "_SIGNAL@MIN1"
    assert compact.dtype == np.float32
    assert np.allclose(compact.to_numpy(), [0.1, 0.2, 0.3])
