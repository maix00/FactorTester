# Copyright 2026 MSD-RS Project LiJia
# SPDX-License-Identifier: BSD-2-Clause

import numpy as np
from . import _algo


def EMA(
  input: np.ndarray | list[np.ndarray], period: int
) -> np.ndarray | list[np.ndarray]:
  """
  Exponential Moving Average (variant of EMA)

  alpha = 2 / (n + 1)

  https://en.wikipedia.org/wiki/Moving_average#Exponential_moving_average

  Args:
    input: input array
    period: period

  Returns:
    output array
  """
  if isinstance(input, list):
    r = [np.empty_like(x) for x in input]
    _algo.ema(r, input, period)
    return r
  else:
    r = np.empty_like(input)
    _algo.ema(r, input, period)
    return r


def session_rolling_sum(values, session_ids, lookback_sessions: int) -> np.ndarray:
  """Rust session-spanning rolling sum (variable bar count per session)."""
  return np.asarray(
    _algo.session_rolling_sum(
      np.asarray(values, dtype=float).tolist(),
      [int(value) for value in session_ids],
      int(lookback_sessions),
    ),
    dtype=float,
  )


def session_rolling_mean(values, session_ids, lookback_sessions: int) -> np.ndarray:
  """Rust session-spanning rolling mean (variable bar count per session)."""
  return np.asarray(
    _algo.session_rolling_mean(
      np.asarray(values, dtype=float).tolist(),
      [int(value) for value in session_ids],
      int(lookback_sessions),
    ),
    dtype=float,
  )








EmaState = _algo.EmaState





IntervalState = _algo.IntervalState


IntervalPairState = _algo.IntervalPairState


def interval_rolling(values, starts, ends, op="mean", quantile=None, window=None):
  """Batch interval aggregation executed in Rust."""
  return np.asarray(
    _algo.interval_rolling(
      np.asarray(values, dtype=float),
      np.asarray(starts, dtype=np.uint64),
      np.asarray(ends, dtype=np.uint64),
      str(op), None if quantile is None else float(quantile),
      None if window is None else int(window),
    ),
    dtype=float,
  )


def interval_rolling_pair(x, y, starts, ends, correlation=False, window=None):
  """Batch interval cov/corr executed in Rust."""
  return np.asarray(
    _algo.interval_rolling_pair(
      np.asarray(x, dtype=float),
      np.asarray(y, dtype=float),
      np.asarray(starts, dtype=np.uint64),
      np.asarray(ends, dtype=np.uint64),
      bool(correlation), None if window is None else int(window),
    ),
    dtype=float,
  )


def interval_ema(values, span: int, min_periods: int = 1, propagate_nan: bool = True):
  """Batch EMA executed in Rust."""
  return np.asarray(
    _algo.interval_ema(
      np.asarray(values, dtype=float), int(span),
      int(min_periods), bool(propagate_nan),
    ),
    dtype=float,
  )
