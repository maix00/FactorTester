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


SessionRollingState = _algo.SessionRollingState


SessionPairState = _algo.SessionPairState


WallRollingState = _algo.WallRollingState


WallPairState = _algo.WallPairState


BarRollingState = _algo.BarRollingState


BarPairState = _algo.BarPairState


EmaState = _algo.EmaState




StartIndexState = _algo.StartIndexState


IntervalState = _algo.IntervalState


IntervalPairState = _algo.IntervalPairState
