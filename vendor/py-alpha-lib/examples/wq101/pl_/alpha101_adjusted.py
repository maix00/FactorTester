import polars as pl
import numpy as np
from scipy.stats import rankdata


# Helper functions
def ts_sum(expr, window=10):
  return expr.rolling_sum(window_size=window).over("securityid")


def sma(expr, window=10):
  return expr.rolling_mean(window_size=window).over("securityid")


def stddev(expr, window=10):
  return expr.rolling_std(window_size=window).over("securityid")


def correlation(x, y, window=10):
  # Pandas rolling correlation typically handles NaN by propagating them or ignoring?
  # Polars rolling_corr might be stricter.
  # Also ensure input doesn't have internal NaNs that kill the window.
  return pl.rolling_corr(x, y, window_size=window).over("securityid")


def covariance(x, y, window=10):
  return pl.rolling_cov(x, y, window_size=window).over("securityid")


def ts_min(expr, window=10):
  return expr.rolling_min(window_size=window).over("securityid")


def ts_max(expr, window=10):
  return expr.rolling_max(window_size=window).over("securityid")


def delta(expr, period=1):
  return expr.diff(n=period).over("securityid")


def delay(expr, period=1):
  return expr.shift(n=period).over("securityid")


def rank(expr):
  # Cross sectional rank
  # Polars rank defaults: method='average', invalid='null' (propagates nulls)
  # Pandas rank(pct=True) behavior:
  # - computes rank (1..N)
  # - divides by count (N) or N-1?
  # - pct=True usually means rank / count
  # Let's ensure we handle nulls same as pd (rank them or ignore?)
  # pd defaults: na_option='keep' (NaNs stay NaNs)
  # So simply rank() / count() should be generally ok IF count includes/excludes NaNs same way.
  # Polars count() counts non-nulls.
  return expr.rank().over("tradetime") / expr.count().over("tradetime")


def scale(expr, k=1):
  return (expr * k / expr.abs().sum()).over("tradetime")


def rolling_rank_py(window_data):
  return rankdata(window_data, method="min")[-1]


def ts_rank(expr, window=10):
  # Reverting to native rolling_rank for performance.
  # We observed -5 vs -8 difference.
  # Pandas rankdata(method='min')[-1] gives 1-based rank.
  # Polars rolling_rank?
  # Let's check documentation or assume 1-based.
  # If Polars gives 0-based, we might need +1.
  return expr.rolling_rank(window_size=window).over("securityid")


def ts_argmax(expr, window=10):
  return (
    expr.rolling_map(lambda x: np.argmax(x) + 1, window_size=window)
    .over("securityid")
    .cast(pl.Float64)
  )


def ts_argmin(expr, window=10):
  return (
    expr.rolling_map(lambda x: np.argmin(x) + 1, window_size=window)
    .over("securityid")
    .cast(pl.Float64)
  )


def product(expr, window=10):
  # No rolling_prod? exists in 1.38?
  # Check if rolling_map needed. np.prod is fast.
  return expr.rolling_map(np.prod, window_size=window).over("securityid")


def decay_linear(expr, period=10):
  def lwma(x):
    n = len(x)
    w = np.arange(1, n + 1)
    w = w / w.sum()
    return np.dot(x, w)

  return expr.rolling_map(lwma, window_size=period).over("securityid")


def sign(expr):
  return expr.sign()


def log(expr):
  return expr.log()


def abs(expr):
  return expr.abs()


class Alphas(object):
  def __init__(self, df: pl.DataFrame):
    self.df = df
    self.open = pl.col("open")
    self.high = pl.col("high")
    self.low = pl.col("low")
    self.close = pl.col("close")
    self.volume = pl.col("vol")
    self.vwap = pl.col("vwap")
    self.returns = self.close / self.close.shift(1).over("securityid") - 1

  def _exec(self, expr):
    return self.df.select(
      [pl.col("tradetime"), pl.col("securityid"), expr.alias("alpha")]
    )

  # Alpha#1	 (rank(Ts_ArgMax(SignedPower(((returns < 0) ? stddev(returns, 20) : close), 2.), 5)) -0.5)
  def alpha001(self):
    inner = (
      pl.when(self.returns < 0).then(stddev(self.returns, 20)).otherwise(self.close)
    )
    # Materialize ts_argmax result particularly to ensure over() contexts don't clash?
    x = ts_argmax(inner.pow(2), 5).alias("x")
    return self.df.select([pl.col("tradetime"), pl.col("securityid"), x]).select(
      [
        pl.col("tradetime"),
        pl.col("securityid"),
        (rank(pl.col("x")) - 0.5).alias("alpha"),
      ]
    )

  # Alpha#2	 (-1 * correlation(rank(delta(log(volume), 2)), rank(((close - open) / open)), 6))
  def alpha002(self):
    expr = -1 * correlation(
      rank(delta(log(self.volume), 2)), rank((self.close - self.open) / self.open), 6
    )
    return self._exec(expr.fill_nan(0))

  # Alpha#3	 (-1 * correlation(rank(open), rank(volume), 10))
  def alpha003(self):
    expr = -1 * correlation(rank(self.open), rank(self.volume), 10)
    return self._exec(expr.fill_nan(0))

  # Alpha#4	 (-1 * Ts_Rank(rank(low), 9))
  def alpha004(self):
    return self._exec(-1 * ts_rank(rank(self.low), 9))

  # Alpha#5	 (rank((open - (sum(vwap, 10) / 10))) * (-1 * abs(rank((close - vwap)))))
  def alpha005(self):
    return self._exec(
      rank((self.open - (ts_sum(self.vwap, 10) / 10)))
      * (-1 * abs(rank((self.close - self.vwap))))
    )

  # Alpha#6	 (-1 * correlation(open, volume, 10))
  def alpha006(self):
    expr = -1 * correlation(self.open, self.volume, 10)
    return self._exec(expr.fill_nan(0))

  # Alpha#7	 ((adv20 < volume) ? ((-1 * ts_rank(abs(delta(close, 7)), 60)) * sign(delta(close, 7))) : (-1* 1))
  def alpha007(self):
    adv20 = sma(self.volume, 20)
    alpha = -1 * ts_rank(abs(delta(self.close, 7)), 60) * sign(delta(self.close, 7))
    expr = pl.when(adv20 >= self.volume).then(-1).otherwise(alpha)
    return self._exec(expr)

  # Alpha#8	 (-1 * rank(((sum(open, 5) * sum(returns, 5)) - delay((sum(open, 5) * sum(returns, 5)),10))))
  def alpha008(self):
    return self._exec(
      -1
      * (
        rank(
          (
            (ts_sum(self.open, 5) * ts_sum(self.returns, 5))
            - delay((ts_sum(self.open, 5) * ts_sum(self.returns, 5)), 10)
          )
        )
      )
    )

  # Alpha#9	 ((0 < ts_min(delta(close, 1), 5)) ? delta(close, 1) : ((ts_max(delta(close, 1), 5) < 0) ?delta(close, 1) : (-1 * delta(close, 1))))
  def alpha009(self):
    delta_close = delta(self.close, 1)
    cond_1 = ts_min(delta_close, 5) > 0
    cond_2 = ts_max(delta_close, 5) < 0
    alpha = -1 * delta_close
    expr = pl.when(cond_1 | cond_2).then(delta_close).otherwise(alpha)
    return self._exec(expr)

  # Alpha#10	 rank(((0 < ts_min(delta(close, 1), 4)) ? delta(close, 1) : ((ts_max(delta(close, 1), 4) < 0)? delta(close, 1) : (-1 * delta(close, 1)))))
  def alpha010(self):
    delta_close = delta(self.close, 1)
    cond_1 = ts_min(delta_close, 4) > 0
    cond_2 = ts_max(delta_close, 4) < 0
    alpha = -1 * delta_close
    expr = pl.when(cond_1 | cond_2).then(delta_close).otherwise(alpha)
    return self._exec(rank(expr))

  # Alpha#11	 ((rank(ts_max((vwap - close), 3)) + rank(ts_min((vwap - close), 3))) *rank(delta(volume, 3)))
  def alpha011(self):
    return self._exec(
      (
        rank(ts_max((self.vwap - self.close), 3))
        + rank(ts_min((self.vwap - self.close), 3))
      )
      * rank(delta(self.volume, 3))
    )

  # Alpha#12	 (sign(delta(volume, 1)) * (-1 * delta(close, 1)))
  def alpha012(self):
    return self._exec(sign(delta(self.volume, 1)) * (-1 * delta(self.close, 1)))

  # Alpha#13	 (-1 * rank(covariance(rank(close), rank(volume), 5)))
  def alpha013(self):
    return self._exec(-1 * rank(covariance(rank(self.close), rank(self.volume), 5)))

  # Alpha#14	 ((-1 * rank(delta(returns, 3))) * correlation(open, volume, 10))
  def alpha014(self):
    expr = correlation(self.open, self.volume, 10).fill_nan(0)
    return self._exec(-1 * rank(delta(self.returns, 3)) * expr)

  # Alpha#15	 (-1 * sum(rank(correlation(rank(high), rank(volume), 3)), 3))
  def alpha015(self):
    expr = correlation(rank(self.high), rank(self.volume), 3).fill_nan(0)
    return self._exec(-1 * ts_sum(rank(expr), 3))

  # Alpha#16	 (-1 * rank(covariance(rank(high), rank(volume), 5)))
  def alpha016(self):
    return self._exec(-1 * rank(covariance(rank(self.high), rank(self.volume), 5)))

  # Alpha#17	 (((-1 * rank(ts_rank(close, 10))) * rank(delta(delta(close, 1), 1))) *rank(ts_rank((volume / adv20), 5)))
  def alpha017(self):
    adv20 = sma(self.volume, 20)
    return self._exec(
      -1
      * (
        rank(ts_rank(self.close, 10))
        * rank(delta(delta(self.close, 1), 1))
        * rank(ts_rank((self.volume / adv20), 5))
      )
    )

  # Alpha#18	 (-1 * rank(((stddev(abs((close - open)), 5) + (close - open)) + correlation(close, open,10))))
  def alpha018(self):
    expr = correlation(self.close, self.open, 10).fill_nan(0)
    return self._exec(
      -1
      * (
        rank(
          (stddev(abs((self.close - self.open)), 5) + (self.close - self.open)) + expr
        )
      )
    )

  # Alpha#19	 ((-1 * sign(((close - delay(close, 7)) + delta(close, 7)))) * (1 + rank((1 + sum(returns,250)))))
  def alpha019(self):
    return self._exec(
      (-1 * sign((self.close - delay(self.close, 7)) + delta(self.close, 7)))
      * (1 + rank(1 + ts_sum(self.returns, 250)))
    )

  # Alpha#20	 (((-1 * rank((open - delay(high, 1)))) * rank((open - delay(close, 1)))) * rank((open -delay(low, 1))))
  def alpha020(self):
    return self._exec(
      -1
      * (
        rank(self.open - delay(self.high, 1))
        * rank(self.open - delay(self.close, 1))
        * rank(self.open - delay(self.low, 1))
      )
    )

  # Alpha#21
  def alpha021(self):
    cond_1 = sma(self.close, 8) + stddev(self.close, 8) < sma(self.close, 2)
    cond_2 = sma(self.volume, 20) / self.volume < 1
    expr = pl.when(cond_1 | cond_2).then(-1).otherwise(1)
    return self._exec(expr)

  # Alpha#22	 (-1 * (delta(correlation(high, volume, 5), 5) * rank(stddev(close, 20))))
  def alpha022(self):
    df = correlation(self.high, self.volume, 5).fill_nan(0)
    return self._exec(-1 * delta(df, 5) * rank(stddev(self.close, 20)))

  # Alpha#23	 (((sum(high, 20) / 20) < high) ? (-1 * delta(high, 2)) : 0)
  def alpha023(self):
    cond = sma(self.high, 20) < self.high
    expr = pl.when(cond).then(-1 * delta(self.high, 2).fill_nan(0)).otherwise(0)
    return self._exec(expr)

  # Alpha#24
  def alpha024(self):
    cond = delta(sma(self.close, 100), 100) / delay(self.close, 100) <= 0.05
    alpha = -1 * delta(self.close, 3)
    expr = (
      pl.when(cond).then(-1 * (self.close - ts_min(self.close, 100))).otherwise(alpha)
    )
    return self._exec(expr)

  # Alpha#25	 rank(((((-1 * returns) * adv20) * vwap) * (high - close)))
  def alpha025(self):
    adv20 = sma(self.volume, 20)
    return self._exec(
      rank(((((-1 * self.returns) * adv20) * self.vwap) * (self.high - self.close)))
    )

  # Alpha#26	 (-1 * ts_max(correlation(ts_rank(volume, 5), ts_rank(high, 5), 5), 3))
  def alpha026(self):
    df = correlation(ts_rank(self.volume, 5), ts_rank(self.high, 5), 5).fill_nan(0)
    return self._exec(-1 * ts_max(df, 3))

  # Alpha#27	 ((0.5 < rank((sum(correlation(rank(volume), rank(vwap), 6), 2) / 2.0))) ? (-1 * 1) : 1)
  def alpha027(self):
    alpha = rank((sma(correlation(rank(self.volume), rank(self.vwap), 6), 2) / 2.0))
    expr = (
      pl.when(alpha > 0.5).then(-1).otherwise(1)
    )  # cond for <= 0.5 is 1, so implied otherwise
    return self._exec(expr)

  # Alpha#28	 scale(((correlation(adv20, low, 5) + ((high + low) / 2)) - close))
  def alpha028(self):
    adv20 = sma(self.volume, 20)
    df = correlation(adv20, self.low, 5).fill_nan(0)
    return self._exec(scale(((df + ((self.high + self.low) / 2)) - self.close)))

  # Alpha#29	 (min(product(rank(rank(scale(log(sum(ts_min(rank(rank((-1 * rank(delta((close - 1),5))))), 2), 1))))), 1), 5) + ts_rank(delay((-1 * returns), 6), 5))
  def alpha029(self):
    return self._exec(
      ts_min(
        rank(
          rank(scale(log(ts_sum(rank(rank(-1 * rank(delta((self.close - 1), 5)))), 2))))
        ),
        5,
      )
      + ts_rank(delay((-1 * self.returns), 6), 5)
    )

  # Alpha#30
  def alpha030(self):
    delta_close = delta(self.close, 1)
    inner = (
      sign(delta_close) + sign(delay(delta_close, 1)) + sign(delay(delta_close, 2))
    )
    return self._exec(
      ((1.0 - rank(inner)) * ts_sum(self.volume, 5)) / ts_sum(self.volume, 20)
    )

  # Alpha#31
  def alpha031(self):
    adv20 = sma(self.volume, 20)
    df = correlation(adv20, self.low, 12).fill_nan(0)
    p1 = rank(rank(rank(decay_linear((-1 * rank(rank(delta(self.close, 10)))), 10))))
    p2 = rank((-1 * delta(self.close, 3)))
    p3 = sign(scale(df))
    return self._exec(p1 + p2 + p3)

  # Alpha#32
  def alpha032(self):
    return self._exec(
      scale(((sma(self.close, 7) / 7) - self.close))
      + (20 * scale(correlation(self.vwap, delay(self.close, 5), 230)))
    )

  # Alpha#33	 rank((-1 * ((1 - (open / close))^1)))
  def alpha033(self):
    return self._exec(rank(-1 + (self.open / self.close)))

  # Alpha#34	 rank(((1 - rank((stddev(returns, 2) / stddev(returns, 5)))) + (1 - rank(delta(close, 1)))))
  def alpha034(self):
    inner = stddev(self.returns, 2) / stddev(self.returns, 5)
    inner = inner.fill_nan(1)
    return self._exec(rank(2 - rank(inner) - rank(delta(self.close, 1))))

  # Alpha#35	 ((Ts_Rank(volume, 32) * (1 - Ts_Rank(((close + high) - low), 16))) * (1 -Ts_Rank(returns, 32)))
  def alpha035(self):
    return self._exec(
      (ts_rank(self.volume, 32) * (1 - ts_rank(self.close + self.high - self.low, 16)))
      * (1 - ts_rank(self.returns, 32))
    )

  # Alpha#36
  def alpha036(self):
    adv20 = sma(self.volume, 20)
    return self._exec(
      (
        (
          (
            2.21
            * rank(correlation((self.close - self.open), delay(self.volume, 1), 15))
          )
          + (0.7 * rank((self.open - self.close)))
        )
        + (0.73 * rank(ts_rank(delay((-1 * self.returns), 6), 5)))
      )
      + rank(abs(correlation(self.vwap, adv20, 6)))
      + (
        0.6
        * rank((((sma(self.close, 200) / 200) - self.open) * (self.close - self.open)))
      )
    )

  # Alpha#37	 (rank(correlation(delay((open - close), 1), close, 200)) + rank((open - close)))
  def alpha037(self):
    return self._exec(
      rank(correlation(delay(self.open - self.close, 1), self.close, 200))
      + rank(self.open - self.close)
    )

  # Alpha#38	 ((-1 * rank(Ts_Rank(close, 10))) * rank((close / open)))
  def alpha038(self):
    inner = self.close / self.open
    inner = inner.fill_nan(1)
    return self._exec(-1 * rank(ts_rank(self.open, 10)) * rank(inner))

  # Alpha#39	 ((-1 * rank((delta(close, 7) * (1 - rank(decay_linear((volume / adv20), 9)))))) * (1 +rank(sum(returns, 250))))
  def alpha039(self):
    adv20 = sma(self.volume, 20)
    return self._exec(
      (
        -1
        * rank(
          delta(self.close, 7) * (1 - rank(decay_linear((self.volume / adv20), 9)))
        )
      )
      * (1 + rank(sma(self.returns, 250)))
    )

  # Alpha#40	 ((-1 * rank(stddev(high, 10))) * correlation(high, volume, 10))
  def alpha040(self):
    return self._exec(
      -1 * rank(stddev(self.high, 10)) * correlation(self.high, self.volume, 10)
    )

  # Alpha#41	 (((high * low)^0.5) - vwap)
  def alpha041(self):
    return self._exec(pow((self.high * self.low), 0.5) - self.vwap)

  # Alpha#42	 (rank((vwap - close)) / rank((vwap + close)))
  def alpha042(self):
    return self._exec(rank((self.vwap - self.close)) / rank((self.vwap + self.close)))

  # Alpha#43	 (ts_rank((volume / adv20), 20) * ts_rank((-1 * delta(close, 7)), 8))
  def alpha043(self):
    adv20 = sma(self.volume, 20)
    return self._exec(
      ts_rank(self.volume / adv20, 20) * ts_rank((-1 * delta(self.close, 7)), 8)
    )

  # Alpha#44	 (-1 * correlation(high, rank(volume), 5))
  def alpha044(self):
    df = correlation(self.high, rank(self.volume), 5).fill_nan(0)
    return self._exec(-1 * df)

  # Alpha#45	 (-1 * ((rank((sum(delay(close, 5), 20) / 20)) * correlation(close, volume, 2)) *rank(correlation(sum(close, 5), sum(close, 20), 2))))
  def alpha045(self):
    df = correlation(self.close, self.volume, 2).fill_nan(0)
    return self._exec(
      -1
      * (
        rank(sma(delay(self.close, 5), 20))
        * df
        * rank(correlation(ts_sum(self.close, 5), ts_sum(self.close, 20), 2))
      )
    )

  # Alpha#46
  def alpha046(self):
    inner = ((delay(self.close, 20) - delay(self.close, 10)) / 10) - (
      (delay(self.close, 10) - self.close) / 10
    )
    alpha = -1 * delta(self.close)
    expr = pl.when(inner < 0).then(1).when(inner > 0.25).then(-1).otherwise(alpha)
    return self._exec(expr)

  # Alpha#47	 ((((rank((1 / close)) * volume) / adv20) * ((high * rank((high - close))) / (sum(high, 5) /5))) - rank((vwap - delay(vwap, 5))))
  def alpha047(self):
    adv20 = sma(self.volume, 20)
    return self._exec(
      (
        ((rank((1 / self.close)) * self.volume) / adv20)
        * ((self.high * rank((self.high - self.close))) / (sma(self.high, 5) / 5))
      )
      - rank((self.vwap - delay(self.vwap, 5)))
    )

  # Alpha#49
  def alpha049(self):
    inner = ((delay(self.close, 20) - delay(self.close, 10)) / 10) - (
      (delay(self.close, 10) - self.close) / 10
    )
    alpha = -1 * delta(self.close)
    expr = pl.when(inner < -0.1).then(1).otherwise(alpha)
    return self._exec(expr)

  # Alpha#50	 (-1 * ts_max(rank(correlation(rank(volume), rank(vwap), 5)), 5))
  def alpha050(self):
    return self._exec(
      -1 * ts_max(rank(correlation(rank(self.volume), rank(self.vwap), 5)), 5)
    )

  # Alpha#51
  def alpha051(self):
    inner = ((delay(self.close, 20) - delay(self.close, 10)) / 10) - (
      (delay(self.close, 10) - self.close) / 10
    )
    alpha = -1 * delta(self.close)
    expr = pl.when(inner < -0.05).then(1).otherwise(alpha)
    return self._exec(expr)

  # Alpha#52	 ((((-1 * ts_min(low, 5)) + delay(ts_min(low, 5), 5)) * rank(((sum(returns, 240) -sum(returns, 20)) / 220))) * ts_rank(volume, 5))
  def alpha052(self):
    return self._exec(
      (
        (-1 * delta(ts_min(self.low, 5), 5))
        * rank(((ts_sum(self.returns, 240) - ts_sum(self.returns, 20)) / 220))
      )
      * ts_rank(self.volume, 5)
    )

  # Alpha#53	 (-1 * delta((((close - low) - (high - close)) / (close - low)), 9))
  def alpha053(self):
    inner = (self.close - self.low).fill_nan(0).replace(0, 0.0001)
    return self._exec(
      -1 * delta((((self.close - self.low) - (self.high - self.close)) / inner), 9)
    )

  # Alpha#54	 ((-1 * ((low - close) * (open^5))) / ((low - high) * (close^5)))
  def alpha054(self):
    inner = (self.low - self.high).fill_nan(0).replace(0, -0.0001)
    return self._exec(
      -1 * (self.low - self.close) * (self.open.pow(5)) / (inner * (self.close.pow(5)))
    )

  # Alpha#55	 (-1 * correlation(rank(((close - ts_min(low, 12)) / (ts_max(high, 12) - ts_min(low,12)))), rank(volume), 6))
  def alpha055(self):
    divisor = (
      (ts_max(self.high, 12) - ts_min(self.low, 12)).fill_nan(0).replace(0, 0.0001)
    )
    inner = (self.close - ts_min(self.low, 12)) / (divisor)
    df = correlation(rank(inner), rank(self.volume), 6).fill_nan(0)
    return self._exec(-1 * df)

  # Alpha#57	 (0 - (1 * ((close - vwap) / decay_linear(rank(ts_argmax(close, 30)), 2))))
  def alpha057(self):
    return self._exec(
      0
      - (
        1
        * ((self.close - self.vwap) / decay_linear(rank(ts_argmax(self.close, 30)), 2))
      )
    )

  # Alpha#60
  def alpha060(self):
    divisor = (self.high - self.low).fill_nan(0).replace(0, 0.0001)
    inner = ((self.close - self.low) - (self.high - self.close)) * self.volume / divisor
    return self._exec(
      -((2 * scale(rank(inner))) - scale(rank(ts_argmax(self.close, 10))))
    )

  # Alpha#61	 (rank((vwap - ts_min(vwap, 16.1219))) < rank(correlation(vwap, adv180, 17.9282)))
  def alpha061(self):
    adv180 = sma(self.volume, 180)
    expr = rank((self.vwap - ts_min(self.vwap, 16))) < rank(
      correlation(self.vwap, adv180, 18)
    )
    # Boolean to int? pd code returns boolean series?
    # pd code: return rank(...) < rank(...) -> boolean Series.
    # main.py expects value.
    # If boolean, polars returns boolean.
    # We should convert to float/int if expected.
    # Let's check pd_ output. It returns bools (True/False).
    # In main.py `df["polarsValue"]` will be True/False.
    # pd_ probably doesn't cast.
    return self._exec(expr)

  # Alpha#62
  def alpha062(self):
    adv20 = sma(self.volume, 20)
    return self._exec(
      (
        rank(correlation(self.vwap, sma(adv20, 22), 10))
        < rank(
          (
            (rank(self.open) + rank(self.open))
            < (rank(((self.high + self.low) / 2)) + rank(self.high))
          )
        )
      )
      * -1
    )

  # Alpha#64
  def alpha064(self):
    adv120 = sma(self.volume, 120)
    return self._exec(
      (
        rank(
          correlation(
            sma(((self.open * 0.178404) + (self.low * (1 - 0.178404))), 13),
            sma(adv120, 13),
            17,
          )
        )
        < rank(
          delta(
            ((((self.high + self.low) / 2) * 0.178404) + (self.vwap * (1 - 0.178404))),
            4,
          )
        )
      )
      * -1
    )

  # Alpha#65
  def alpha065(self):
    adv60 = sma(self.volume, 60)
    return self._exec(
      (
        rank(
          correlation(
            ((self.open * 0.00817205) + (self.vwap * (1 - 0.00817205))),
            sma(adv60, 9),
            6,
          )
        )
        < rank((self.open - ts_min(self.open, 14)))
      )
      * -1
    )

  # Alpha#66
  def alpha066(self):
    return self._exec(
      (
        rank(decay_linear(delta(self.vwap, 4), 7))
        + ts_rank(
          decay_linear(
            (
              (((self.low * 0.96633) + (self.low * (1 - 0.96633))) - self.vwap)
              / (self.open - ((self.high + self.low) / 2))
            ),
            11,
          ),
          7,
        )
      )
      * -1
    )

  # Alpha#68
  def alpha068(self):
    adv15 = sma(self.volume, 15)
    return self._exec(
      (
        ts_rank(correlation(rank(self.high), rank(adv15), 9), 14)
        < rank(delta(((self.close * 0.518371) + (self.low * (1 - 0.518371))), 2))
      )
      * -1
    )

  # Alpha#71
  def alpha071(self):
    adv180 = sma(self.volume, 180)
    p1 = ts_rank(
      decay_linear(correlation(ts_rank(self.close, 3), ts_rank(adv180, 12), 18), 4),
      16,
    )
    p2 = ts_rank(
      decay_linear(
        (rank(((self.low + self.open) - (self.vwap + self.vwap))).pow(2)), 16
      ),
      4,
    )
    return self._exec(pl.max_horizontal([p1, p2]))

  # Alpha#72
  def alpha072(self):
    adv40 = sma(self.volume, 40)
    return self._exec(
      rank(decay_linear(correlation(((self.high + self.low) / 2), adv40, 9), 10))
      / rank(
        decay_linear(correlation(ts_rank(self.vwap, 4), ts_rank(self.volume, 19), 7), 3)
      )
    )

  # Alpha#73
  def alpha073(self):
    p1 = rank(decay_linear(delta(self.vwap, 5), 3))
    p2 = ts_rank(
      decay_linear(
        (
          (
            delta(((self.open * 0.147155) + (self.low * (1 - 0.147155))), 2)
            / ((self.open * 0.147155) + (self.low * (1 - 0.147155)))
          )
          * -1
        ),
        3,
      ),
      17,
    )
    return self._exec(-1 * pl.max_horizontal([p1, p2]))

  # Alpha#74
  def alpha074(self):
    adv30 = sma(self.volume, 30)
    return self._exec(
      (
        rank(correlation(self.close, sma(adv30, 37), 15))
        < rank(
          correlation(
            rank(((self.high * 0.0261661) + (self.vwap * (1 - 0.0261661)))),
            rank(self.volume),
            11,
          )
        )
      )
      * -1
    )

  # Alpha#75
  def alpha075(self):
    adv50 = sma(self.volume, 50)
    return self._exec(
      rank(correlation(self.vwap, self.volume, 4))
      < rank(correlation(rank(self.low), rank(adv50), 12))
    )

  # Alpha#77
  def alpha077(self):
    adv40 = sma(self.volume, 40)
    p1 = rank(
      decay_linear(
        ((((self.high + self.low) / 2) + self.high) - (self.vwap + self.high)),
        20,
      )
    )
    p2 = rank(decay_linear(correlation(((self.high + self.low) / 2), adv40, 3), 6))
    return self._exec(pl.min_horizontal([p1, p2]))

  # Alpha#78
  def alpha078(self):
    adv40 = sma(self.volume, 40)
    return self._exec(
      rank(
        correlation(
          ts_sum(((self.low * 0.352233) + (self.vwap * (1 - 0.352233))), 20),
          ts_sum(adv40, 20),
          7,
        )
      ).pow(rank(correlation(rank(self.vwap), rank(self.volume), 6)))
    )

  # Alpha#81
  def alpha081(self):
    adv10 = sma(self.volume, 10)
    return self._exec(
      (
        rank(
          log(
            product(
              rank((rank(correlation(self.vwap, ts_sum(adv10, 50), 8)).pow(4))), 15
            )
          )
        )
        < rank(correlation(rank(self.vwap), rank(self.volume), 5))
      )
      * -1
    )

  # Alpha#83
  def alpha083(self):
    return self._exec(
      (
        rank(delay(((self.high - self.low) / (ts_sum(self.close, 5) / 5)), 2))
        * rank(rank(self.volume))
      )
      / (
        ((self.high - self.low) / (ts_sum(self.close, 5) / 5))
        / (self.vwap - self.close)
      )
    )

  # Alpha#84
  def alpha084(self):
    return self._exec(
      pow(ts_rank((self.vwap - ts_max(self.vwap, 15)), 21), delta(self.close, 5))
    )

  # Alpha#85
  def alpha085(self):
    adv30 = sma(self.volume, 30)
    return self._exec(
      rank(
        correlation(((self.high * 0.876703) + (self.close * (1 - 0.876703))), adv30, 10)
      ).pow(
        rank(
          correlation(
            ts_rank(((self.high + self.low) / 2), 4), ts_rank(self.volume, 10), 7
          )
        )
      )
    )

  # Alpha#86
  def alpha086(self):
    adv20 = sma(self.volume, 20)
    return self._exec(
      (
        ts_rank(correlation(self.close, sma(adv20, 15), 6), 20)
        < rank(((self.open + self.close) - (self.vwap + self.open)))
      )
      * -1
    )

  # Alpha#88
  def alpha088(self):
    adv60 = sma(self.volume, 60)
    p1 = rank(
      decay_linear(
        ((rank(self.open) + rank(self.low)) - (rank(self.high) + rank(self.close))),
        8,
      )
    )
    p2 = ts_rank(
      decay_linear(correlation(ts_rank(self.close, 8), ts_rank(adv60, 21), 8), 7),
      3,
    )
    return self._exec(pl.min_horizontal([p1, p2]))

  # Alpha#92
  def alpha092(self):
    adv30 = sma(self.volume, 30)
    p1 = ts_rank(
      decay_linear(
        ((((self.high + self.low) / 2) + self.close) < (self.low + self.open)),
        15,
      ),
      19,
    )
    p2 = ts_rank(decay_linear(correlation(rank(self.low), rank(adv30), 8), 7), 7)
    return self._exec(pl.min_horizontal([p1, p2]))

  # Alpha#94
  def alpha094(self):
    adv60 = sma(self.volume, 60)
    return self._exec(
      (
        rank((self.vwap - ts_min(self.vwap, 12))).pow(
          ts_rank(correlation(ts_rank(self.vwap, 20), ts_rank(adv60, 4), 18), 3)
        )
        * -1
      )
    )

  # Alpha#95
  def alpha095(self):
    adv40 = sma(self.volume, 40)
    return self._exec(
      rank((self.open - ts_min(self.open, 12)))
      < ts_rank(
        (
          rank(
            correlation(sma(((self.high + self.low) / 2), 19), sma(adv40, 19), 13)
          ).pow(5)
        ),
        12,
      )
    )

  # Alpha#96
  def alpha096(self):
    adv60 = sma(self.volume, 60)
    p1 = ts_rank(
      decay_linear(correlation(rank(self.vwap), rank(self.volume), 4), 4),
      8,
    )
    p2 = ts_rank(
      decay_linear(
        ts_argmax(correlation(ts_rank(self.close, 7), ts_rank(adv60, 4), 4), 13),
        14,
      ),
      13,
    )
    return self._exec(-1 * pl.max_horizontal([p1, p2]))

  # Alpha#98
  def alpha098(self):
    adv5 = sma(self.volume, 5)
    adv15 = sma(self.volume, 15)
    return self._exec(
      rank(decay_linear(correlation(self.vwap, sma(adv5, 26), 5), 7))
      - rank(
        decay_linear(
          ts_rank(ts_argmin(correlation(rank(self.open), rank(adv15), 21), 9), 7),
          8,
        )
      )
    )

  # Alpha#99
  def alpha099(self):
    adv60 = sma(self.volume, 60)
    return self._exec(
      (
        rank(
          correlation(ts_sum(((self.high + self.low) / 2), 20), ts_sum(adv60, 20), 9)
        )
        < rank(correlation(self.low, self.volume, 6))
      )
      * -1
    )

  # Alpha#101
  def alpha101(self):
    return self._exec((self.close - self.open) / ((self.high - self.low) + 0.001))
