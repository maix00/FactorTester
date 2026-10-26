# Copyright 2026 MSD-RS Project LiJia
# SPDX-License-Identifier: BSD-2-Clause

from .algo import (
    BatchPlan, EmaState, FactorPlanState, IntervalPairState, IntervalState,
    bar_since, cross_sectional, interval_ema, interval_rolling,
    interval_rolling_pair, session_rolling_mean, session_rolling_sum,
)
from .lang import *
from .context import ExecContext
from . import factor


# skip nan values during computations
FLAG_SKIP_NAN: int = 1
# strictly cycle over the data
FLAG_STRICTLY_CYCLE: int = 2
