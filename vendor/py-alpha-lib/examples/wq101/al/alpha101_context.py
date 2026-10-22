import numpy as np
import alpha
from alpha.context import _fill_panel, _extract_cols


def returns(a: np.ndarray):
  return a / alpha.REF(a, 1) - 1


class ExecContext:
  def __init__(self, data, fill: bool = True):
    # Auto-infer groups from data
    securities = 0
    trades = 0
    try:
      securities = data["securityid"].n_unique()
      trades = data["tradetime"].n_unique()
    except Exception:
      try:
        securities = data["securityid"].nunique()
        trades = data["tradetime"].nunique()
      except Exception:
        pass
    if securities > 0:
      alpha.set_ctx(groups=securities)

    _cols = ["open", "high", "low", "close", "vol", "vwap"]
    # Include optional columns if available in data
    _has_indclass = False
    _has_cap = False
    try:
      _ = data["indclass"]
      _has_indclass = True
      _cols.append("indclass")
    except Exception:
      pass
    try:
      _ = data["cap"]
      _has_cap = True
      _cols.append("cap")
    except Exception:
      pass

    if fill and securities > 0 and trades > 0:
      d = _fill_panel(data, securities, trades, _cols)
    else:
      d = _extract_cols(data, _cols)

    self.OPEN = d["open"]
    self.HIGH = d["high"]
    self.LOW = d["low"]
    self.CLOSE = d["close"]
    self.VOLUME = d["vol"].astype(np.float64)
    self.RETURNS = returns(d["close"])
    self.VWAP = d["vwap"]

    if _has_indclass:
      indclass = d["indclass"]
      self.INDCLASS_SUBINDUSTRY = indclass
      self.INDCLASS_INDUSTRY = np.floor(indclass / 10000)
      self.INDCLASS_SECTOR = np.floor(indclass / 1000000)
    if _has_cap:
      self.CAP = d["cap"].astype(np.float64)

  def __call__(self, name: str) -> np.ndarray:
    if name.startswith("ADV"):
      n = name[3:]
      if len(n) == 0:
        return self.VOLUME
      else:
        w = int(n)
        return self.SMA(self.VOLUME, w)
    if name.startswith("INDCLASS."):
      return getattr(self, name.replace(".", "_"))
    return getattr(self, name)

  def SUM(self, a: np.ndarray, w: int) -> np.ndarray:
    return alpha.SUM(a, int(w))

  def SMA(self, a: np.ndarray, w: int) -> np.ndarray:
    return alpha.MA(a, int(w))

  def STDDEV(self, a: np.ndarray, w: int) -> np.ndarray:
    return alpha.STDDEV(a, int(w))

  def CORRELATION(self, a: np.ndarray, b: np.ndarray, w: int) -> np.ndarray:
    return alpha.CORR2(a, b, int(w))

  def COVARIANCE(self, a: np.ndarray, b: np.ndarray, w: int) -> np.ndarray:
    return alpha.COV(a, b, int(w))

  def TS_RANK(self, a: np.ndarray, w: int) -> np.ndarray:
    return alpha.RANK(a, int(w))

  def PRODUCT(self, a: np.ndarray, w: int) -> np.ndarray:
    return alpha.PRODUCT(a, int(w))

  def TS_MIN(self, a: np.ndarray, w: int) -> np.ndarray:
    return alpha.LLV(a, int(w))

  def MIN(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.minimum(a, b)

  def TS_MAX(self, a: np.ndarray, w: int) -> np.ndarray:
    return alpha.HHV(a, int(w))

  def MAX(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.maximum(a, b)

  def DELTA(self, a: np.ndarray, p: int) -> np.ndarray:
    return a - alpha.REF(a, int(p))

  def DELAY(self, a: np.ndarray, p: int) -> np.ndarray:
    return alpha.REF(a, int(p))

  def SCALE(self, a: np.ndarray, k: int = 1) -> np.ndarray:
    sum = np.abs(a).sum()
    return a * k / sum

  def RANK(self, a: np.ndarray) -> np.ndarray:
    return alpha.CC_RANK(np.asarray(a, dtype=np.float64))

  def TS_ARGMAX(self, a: np.ndarray, w: int) -> np.ndarray:
    return w - alpha.HHVBARS(a, int(w))

  def TS_ARGMIN(self, a: np.ndarray, w: int) -> np.ndarray:
    return w - alpha.LLVBARS(a, int(w))

  def DECAY_LINEAR(self, a: np.ndarray, w: int) -> np.ndarray:
    return alpha.LWMA(np.asarray(a, dtype=np.float64), int(w))

  def SIGNEDPOWER(self, a: np.ndarray, p: float | np.ndarray) -> np.ndarray:
    return np.sign(a) * np.power(np.abs(a), p)

  def LOG(self, a: np.ndarray) -> np.ndarray:
    return np.log(a)

  def ABS(self, a: np.ndarray) -> np.ndarray:
    return np.abs(a)

  def SIGN(self, a: np.ndarray) -> np.ndarray:
    return np.sign(a)

  def INDNEUTRALIZE(self, value: np.ndarray, category: np.ndarray) -> np.ndarray:
    return alpha.NEUTRALIZE(category, value)
