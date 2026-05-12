"""
OPEN-TO-OPEN 下一期收益率时间对齐验证 (refs #6)

用真实品种 A.DCE 的日频和分钟数据，逐步验证 IC 测试中 RE 公式的时间对齐。

CrossSectionIC.factor_expr() 中 RE 公式：
  RE = (SC.delta(RF) / SC.shift(RF)).shift(-RF).shift(S - 1)
  SC=OPEN_ADJUSTED, S=0 → RE = (OA.delta(RF)/OA.shift(RF)).shift(-RF).shift(-1)

数据源：
  日频:  ../data/main_series_adjusted.parquet (主力连续合约)
  分钟:  ../data/main_mink/A.DCE.parquet (1分钟K线)

复权: OA = open_price * adjustment_mul + adjustment_add
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

_DATA_DIR = '/Users/maxdeux/Documents/GTHT/data'

def sep(title):
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")


def compute_oa(df):
    """计算复权开盘价 OA = open_price * adjustment_mul + adjustment_add"""
    return df['open_price'] * df['adjustment_mul'] + df['adjustment_add']


def load_daily():
    path = os.path.join(_DATA_DIR, 'main_series_adjusted.parquet')
    df = pd.read_parquet(path)
    df = df[df['unique_instrument_id'] == 'A.DCE'].copy()
    df = df.sort_values('trading_day').tail(15)
    df['OA'] = compute_oa(df)
    df['date'] = pd.to_datetime(df['trading_day'])
    return df.set_index('date').sort_index()


def load_minute():
    path = os.path.join(_DATA_DIR, 'main_mink', 'A.DCE.parquet')
    df = pd.read_parquet(path)
    df['trading_day'] = pd.to_datetime(df['trading_day'])
    df['trade_time'] = pd.to_datetime(df['trade_time'])
    days = sorted(df['trading_day'].unique())[-3:]
    df = df[df['trading_day'].isin(days)].copy()
    df['OA'] = compute_oa(df)
    return df


def analyze_daily(df):
    """场景1：日度因子，逐步展示每个中间值"""
    sep("场景 1：日度因子 (freq=1d, SC=OPEN_ADJUSTED)")
    OA = df['OA']

    # 步骤1: OA.delta(1d) = OA(t) - OA(t-1)
    delta = OA - OA.shift(1)
    # 步骤2: OA.shift(1d) = OA(t-1)
    shift1 = OA.shift(1)
    # 步骤3: ret_raw = OA.delta(1d) / OA.shift(1d)
    ret_raw = delta / shift1
    # 步骤4: ret_raw.shift(-1d)
    ret_s1 = ret_raw.shift(-1)
    # 步骤5: RE_sys = ret_raw.shift(-1d).shift(-1)
    RE_sys = ret_raw.shift(-2)
    # 正确 RE: 只有 .shift(-1d)
    RE_correct = ret_raw.shift(-1)

    N = len(OA)
    print(f"\n品种: A.DCE (黄豆一号期货, DCE)")
    print(f"数据源: ../data/main_series_adjusted.parquet (日频主力连续)")
    print(f"交易日数: {N}, 日期区间: {OA.index[0].date()} ~ {OA.index[-1].date()}")
    print(f"复权系数: adjustment_mul=1.0, adjustment_add=0 (所选时段无除权)")
    print(f"\n公式分解:")
    print(f"  OA.delta(1d) = OA(t) - OA(t-1)")
    print(f"  OA.shift(1d) = OA(t-1)")
    print(f"  ret_raw      = OA.delta / OA.shift")
    print(f"  .shift(-1d)  → ret_raw 前移 1 天 (到达 t+1)")
    print(f"  .shift(-1)   → 再前移 1 天 (到达 t+2)  ← 多移 1 天！")

    print(f"\n逐步数值:")
    print(f"{'日期':<14} {'OA(t)':>10} {'OA(t-1)':>10} {'delta':>10} {'ret_raw':>10} "
          f"{'→sft-1d':>12} {'RE_sys(t+2)':>13} {'RE_cor(t+1)':>13}")
    print(f"{'-'*14} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*12} {'-'*13} {'-'*13}")

    for i in range(N):
        t = OA.index[i].date()
        vals = [OA.iloc[i], shift1.iloc[i], delta.iloc[i], ret_raw.iloc[i],
                ret_s1.iloc[i], RE_sys.iloc[i], RE_correct.iloc[i]]
        parts = [f"{str(t):<14}"]
        for v in vals:
            parts.append(f"{v:>10.2f}" if not pd.isna(v) else f"{'N/A':>10}")
        print(" ".join(parts))

    print(f"\n对齐验证 (RE 值对应哪个交易日的信号):")
    print(f"{'日期':<14} {'RE_sys':>10} {'→信号日':>12} {'RE_correct':>10} {'→信号日':>12} {'偏差':>6}")
    print(f"{'-'*14} {'-'*10} {'-'*12} {'-'*10} {'-'*12} {'-'*6}")
    for i in range(2, N):
        t = OA.index[i].date()
        rs = RE_sys.iloc[i]
        rc = RE_correct.iloc[i]
        sys_sig = OA.index[i-2].date() if not pd.isna(rs) else ''
        cor_sig = OA.index[i-1].date() if not pd.isna(rc) else ''
        bias = '2天' if not pd.isna(rs) else ''
        print(f"{str(t):<14} {rs:>10.4f} {str(sys_sig):>12} {rc:>10.4f} {str(cor_sig):>12} {bias:>6}")

    print(f"\n结论: .shift(-1) 把 RE 从 t+1 推到了 t+2，多了 1 天。")
    print(f"t 日信号计算 IC 时应对应 t+1 日收益率，实际却用了 t+2 日。")


def analyze_intraday(df):
    """场景2：日内因子，用真实分钟 A.DCE 数据"""
    sep("场景 2：日内因子 (freq=1min, SC=OPEN_ADJUSTED)")

    bars_per_day = df.groupby('trading_day').size()
    n = bars_per_day.iloc[0]
    N = len(df)
    days = [str(d.date()) for d in bars_per_day.index]

    OA = df['OA'].values.astype(np.float64)
    times = df['trade_time']

    # ret_raw = OA(t) / OA(t-n) - 1
    ret_raw = np.full(N, np.nan)
    for i in range(n, N):
        ret_raw[i] = OA[i] / OA[i-n] - 1

    # RE_sys = ret_raw 前移 n+1
    RE_sys = np.full(N, np.nan)
    for i in range(N - n - 1):
        RE_sys[i] = ret_raw[i + n + 1]

    # RE_correct = ret_raw 只前移 n
    RE_correct = np.full(N, np.nan)
    for i in range(N - n):
        RE_correct[i] = ret_raw[i + n]

    print(f"\n品种: A.DCE (黄豆一号期货, DCE)")
    print(f"数据源: ../data/main_mink/A.DCE.parquet (1分钟K线)")
    print(f"交易日: {days}")
    print(f"每日 bar 数: {bars_per_day.tolist()}")
    print(f"n = {n}, 总 bar 数: {N}")
    print(f"\n公式分解:")
    print(f"  OA.delta(1d) = OA(t) - OA(t-{n})")
    print(f"  OA.shift(1d) = OA(t-{n})")
    print(f"  ret_raw      = OA.delta / OA.shift")
    print(f"  .shift(-RF)  = .shift(-{n})  → ret_raw 前移 {n} bars")
    print(f"  .shift(-1)   → 再前移 1 bar (共 {n+1} bars) ← 多移 1 bar")

    print(f"\n关键验证 (多移 1 bar 的数值影响):")
    print(f"  ret_raw[{n}]   = {ret_raw[n]:.6f}  (第2天第1个bar, OA={OA[n]:.2f}, OA[{n}-{n}]={OA[0]:.2f})")
    print(f"  ret_raw[{n+1}] = {ret_raw[n+1]:.6f}  (第2天第2个bar, OA={OA[n+1]:.2f}, OA[{n+1}-{n}]={OA[1]:.2f})")
    print(f"  RE_correct[0] = ret_raw[{n}]   = {RE_correct[0]:.6f}  (应该的值)")
    print(f"  RE_sys[0]     = ret_raw[{n+1}] = {RE_sys[0]:.6f}  (实际的值)")
    print(f"  差值 = |{RE_sys[0]:.6f} - {RE_correct[0]:.6f}| = {abs(RE_sys[0] - RE_correct[0]):.6f}")

    # 前10行对比
    print(f"\n前 10 行对比:")
    print(f"{'bar':>5} {'time':<22} {'OA(t)':>10} {'OA(t-n)':>10} {'ret_raw':>10} "
          f"{'RE_sys':>12} {'RE_cor':>12} {'相同?':>8}")
    print(f"{'-'*5} {'-'*22} {'-'*10} {'-'*10} {'-'*10} {'-'*12} {'-'*12} {'-'*8}")
    for i in range(min(10, N)):
        oa_tn = OA[i-n] if i >= n else np.nan
        same = ''
        if not np.isnan(RE_sys[i]) and not np.isnan(RE_correct[i]):
            same = 'Y' if abs(RE_sys[i] - RE_correct[i]) < 1e-9 else 'N'
        print(f"{i:>5} {str(times.iloc[i]):<22} {OA[i]:>10.2f} "
              f"{oa_tn:>10.2f}" if not np.isnan(oa_tn) else f"{i:>5} {str(times.iloc[i]):<22} {OA[i]:>10.2f} {'N/A':>10}",
              end="")
        print(f" {ret_raw[i]:>10.4f}" if not np.isnan(ret_raw[i]) else " {'N/A':>10}", end="")
        print(f" {RE_sys[i]:>12.4f}" if not np.isnan(RE_sys[i]) else " {'N/A':>12}", end="")
        print(f" {RE_correct[i]:>12.4f}" if not np.isnan(RE_correct[i]) else " {'N/A':>12}", end="")
        print(f" {same:>8}")

    # 统计差异
    diff = (RE_sys - RE_correct)
    valid = ~np.isnan(diff)
    if valid.any():
        print(f"\n差异统计:")
        print(f"  有效比较点: {valid.sum()}")
        print(f"  最大绝对差: {np.abs(diff[valid]).max():.6f}")
        print(f"  平均绝对差: {np.abs(diff[valid]).mean():.6f}")
        print(f"  RE_sys ≠ RE_correct 的比例: {(np.abs(diff[valid]) > 1e-9).sum()}/{valid.sum()}")

    print(f"\n结论: .shift(-1) 导致 RE 时间偏移 1 bar + 数值差异 ({abs(RE_sys[0] - RE_correct[0]):.4%})。")
    print(f"OA 在分钟级别随 bar 变化，多移 1 bar 会取到不同的 ret_raw 值。")


if __name__ == '__main__':
    sep("OPEN-TO-OPEN 收益率时间对齐分析")
    print(f"\n品种: A.DCE (黄豆一号期货, 大连商品交易所 DCE)")
    print(f"SC: OPEN_ADJUSTED (复权开盘价)")
    print(f"RF: 1d")
    print(f"\nCrossSectionIC.factor_expr() RE公式:")
    print(f"  RE = (SC.delta(RF)/SC.shift(RF)).shift(-RF).shift(S-1)")
    print(f"  S=0(OPEN) → RE = (OA.delta(1d)/OA.shift(1d)).shift(-1d).shift(-1)")
    print(f"                                         shift(-RF)     shift(S-1)")

    print(f"\n{'-'*80}")
    print(f"数据路径 (相对 Codes 目录):")
    d1 = os.path.join(_DATA_DIR, 'main_series_adjusted.parquet')
    d2 = os.path.join(_DATA_DIR, 'main_mink', 'A.DCE.parquet')
    print(f"  日频: {os.path.relpath(d1, os.getcwd())}")
    print(f"  分钟: {os.path.relpath(d2, os.getcwd())}")

    # 场景1: 日度
    df_daily = load_daily()
    analyze_daily(df_daily)

    # 场景2: 日内
    df_minute = load_minute()
    analyze_intraday(df_minute)
    print()
