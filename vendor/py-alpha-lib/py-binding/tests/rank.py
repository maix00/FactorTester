import pandas as pd
import numpy as np
import alpha


df = pd.DataFrame(
  data={
    "Animal": ["cat", "penguin", "dog", "spider", "snake"],
    "Number_legs": [4, 2, 4, 8, 0],
  }
)

def test_log_delta_rank_chain_panics():
  """模拟修复前 alpha_002 的 LOG→DELTA(2)→RANK 链路即复现线上 panic"""
  rng = np.random.default_rng(17)
  n = 32
  # t=4 目标截面（已验证稳定触发 Rust total-order 校验 panic 的 recipe）
  target = rng.normal(size=n)
  pos = rng.permutation(n)
  nn = max(1, int(n * rng.uniform(0.1, 0.3)))
  target[pos[:nn]] = np.nan
  target[pos[nn % n]] = np.inf
  target[pos[(nn + 1) % n]] = -np.inf
  # 反推成交量，使 delta(log(vol),2) 在 t=4 的截面 == target
  vol = np.full((n, 6), 1000.0)
  nan_m = np.isnan(target)
  posinf_m = np.isposinf(target)
  neginf_m = np.isneginf(target)
  vol[nan_m, 2] = np.nan               # 停牌 → delta=NaN
  vol[posinf_m, 2] = 0.0               # LOG(0)=-inf → delta=+inf
  vol[neginf_m, 4] = 0.0               # delta=-inf
  fin_m = ~(nan_m | posinf_m | neginf_m)
  vol[fin_m, 4] = 1000.0 * np.exp(target[fin_m])  # delta=target
  # 算子链路：LOG → DELTA(2) → 截面 RANK（与 ctx.LOG/ctx.DELTA 同语义）
  with np.errstate(divide='ignore', invalid='ignore'):
    log_vol = np.log(vol)
  delta = log_vol[:, 2:] - log_vol[:, :-2]
  # t=4 截面（NaN+±inf 混排）；列切片为非连续视图，须连续化（绑定层提取要求 contiguous，
  # 否则抛 ValueError "failed to get slice"）
  cross = np.ascontiguousarray(delta[:, 2])
  alpha.set_ctx(groups=n)
  print(len(cross), n)
  r = np.empty_like(cross)
  print(alpha.CC_RANK(cross))


alpha.set_ctx(groups=5)
print(alpha.RANK(df["Number_legs"].to_numpy().astype(np.float64), 1))
print(df["Number_legs"].rank(pct=True).to_numpy().astype(np.float64))

alpha.set_ctx(groups=3)
print(alpha.CC_RANK(np.array([3.0, np.nan, 1.0, np.inf, 4.0, -np.inf]*50)))

test_log_delta_rank_chain_panics()