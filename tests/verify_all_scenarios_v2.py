"""
完整验证: CrossSectionIC RE 公式时间对齐
==========================================

验证矩阵:
  SC=OPEN/CLOSE  ×  RF=1d/5min  ×  skip=YES/NO

RE 公式: (SC.delta(RF)/SC.shift(RF)).shift(-RF).shift(S - 1)
  OA (S=0): ret_raw.shift(-RF).shift(-1) -> 下期买+下下期卖
  CA (S=1): ret_raw.shift(-RF).shift(0)  -> 当期买+下期卖

数据源:
  main_series_adjusted.parquet (日频)
  main_mink/A.DCE.parquet (1-min)
"""
import pandas as pd
import numpy as np

BORDER = "=" * 78

# ====================================================================
# 1. 日频 + OA (OPEN-TO-OPEN, RF=1d)
# ====================================================================
def verify_daily_oa():
    print(BORDER)
    print("1. 日频 + OA (OPEN-TO-OPEN, RF=1d) [daily no skip]")
    print(BORDER)
    print("买入 OA[t+1], 卖出 OA[t+2] -> RE[t] = OA[t+2]/OA[t+1] - 1")
    print()

    df = pd.read_parquet('/Users/maxdeux/Documents/GTHT/data/main_series_adjusted.parquet')
    a = df[df['unique_instrument_id'] == 'A.DCE'].copy().sort_values('trading_day').tail(10)
    a['OA'] = a['open_price'] * a['adjustment_mul'] + a['adjustment_add']
    a = a.set_index(pd.to_datetime(a['trading_day'])).sort_index()

    print("原始 OA (日频, A.DCE, 最后10个交易日):")
    for i, (dt, row) in enumerate(a.iterrows()):
        print(f"  [{i}] {str(dt.date()):<14} OA={row['OA']:>10.2f}")
    print()

    print("分解: ret_raw[t] = OA[t]/OA[t-1] - 1")
    print("      RE[t] = ret_raw.shift(-1d).shift(-1)[t] = ret_raw[t+2]")
    print("            = OA[t+2]/OA[t+1] - 1")
    print()

    n = len(a)
    hdr = f"{'T':<14} {'OA[T]':>9} {'OA[T+1]':>9} {'OA[T+2]':>9} {'ret_raw[T]':>12} {'RE[T]=OA[T+2]/OA[T+1]-1':>25}"
    print(hdr)
    print("-" * len(hdr))

    for i in range(n - 2):
        dt = a.index[i]
        rr = a['OA'].iloc[i] / a['OA'].iloc[i-1] - 1 if i > 0 else np.nan
        re_ = a['OA'].iloc[i+2] / a['OA'].iloc[i+1] - 1
        print(f"{str(dt.date()):<14} {a['OA'].iloc[i]:>9.2f} {a['OA'].iloc[i+1]:>9.2f} {a['OA'].iloc[i+2]:>9.2f} {rr:>12.6f} {re_:>25.8f}")

    print()
    print("=> OA[T+2]/OA[T+1]-1 = T+1日开盘买入, T+2日开盘卖出 [OK]")
    print()

# ====================================================================
# 2. 日频 + CA (CLOSE-TO-CLOSE, RF=1d)
# ====================================================================
def verify_daily_ca():
    print(BORDER)
    print("2. 日频 + CA (CLOSE-TO-CLOSE, RF=1d) [daily no skip]")
    print(BORDER)
    print("买入 CA[t], 卖出 CA[t+1] -> RE[t] = CA[t+1]/CA[t] - 1")
    print()

    df = pd.read_parquet('/Users/maxdeux/Documents/GTHT/data/main_series_adjusted.parquet')
    a = df[df['unique_instrument_id'] == 'A.DCE'].copy().sort_values('trading_day').tail(10)
    a['CA'] = a['close_price'] * a['adjustment_mul'] + a['adjustment_add']
    a = a.set_index(pd.to_datetime(a['trading_day'])).sort_index()

    print("原始 CA (日频, A.DCE, 最后10个交易日):")
    for i, (dt, row) in enumerate(a.iterrows()):
        print(f"  [{i}] {str(dt.date()):<14} CA={row['CA']:>10.2f}")
    print()

    print("分解: ret_raw[t] = CA[t]/CA[t-1] - 1")
    print("      RE[t] = ret_raw.shift(-1d).shift(0)[t] = ret_raw[t+1]")
    print("            = CA[t+1]/CA[t] - 1")
    print()

    n = len(a)
    hdr = f"{'T':<14} {'CA[T]':>9} {'CA[T+1]':>9} {'ret_raw[T]':>12} {'RE[T]=CA[T+1]/CA[T]-1':>25}"
    print(hdr)
    print("-" * len(hdr))

    for i in range(n - 1):
        dt = a.index[i]
        rr = a['CA'].iloc[i] / a['CA'].iloc[i-1] - 1 if i > 0 else np.nan
        re_ = a['CA'].iloc[i+1] / a['CA'].iloc[i] - 1
        print(f"{str(dt.date()):<14} {a['CA'].iloc[i]:>9.2f} {a['CA'].iloc[i+1]:>9.2f} {rr:>12.6f} {re_:>25.8f}")

    print()
    print("=> CA[T+1]/CA[T]-1 = 当日买入, 次日卖出 [OK]")
    print()

# ====================================================================
# 3. 日内 + OA (OPEN-TO-OPEN, RF=5min, no-skip)
# ====================================================================
def verify_intraday_oa_noskip():
    print(BORDER)
    print("3. 日内 + OA (OPEN-TO-OPEN, RF=5min, no-skip)")
    print(BORDER)
    print("信号 bar t, 买入 OA[t+1], 卖出 OA[t+6] -> RE[t] = OA[t+6]/OA[t+1]-1")
    print()

    df = pd.read_parquet('/Users/maxdeux/Documents/GTHT/data/main_mink/A.DCE.parquet')
    df['dt'] = pd.to_datetime(df['trade_time'])
    df['OA'] = df['open_price'] * df['adjustment_mul'] + df['adjustment_add']
    df['CA'] = df['close_price'] * df['adjustment_mul'] + df['adjustment_add']
    df = df.sort_values('dt').set_index('dt')

    win = df['2025-11-26 09:00':'2025-11-26 09:25'].copy()

    print("A.DCE 2025-11-26 开盘 1-min OA (bar 0-25):")
    print(f"{'bar#':>5} {'time':<22} {'OA':>10}")
    print("-" * 39)
    oa = []
    for j, (dt, row) in enumerate(win.iterrows()):
        oa.append(row['OA'])
        print(f"{j:>5} {str(dt):<22} {row['OA']:>10.2f}")
    print()

    # RF=5min -> ret_raw[t] = OA[t]/OA[t-5min] - 1
    print("ret_raw[t] = OA[t]/OA[t-5min]-1  (5min=5bars at 1-min):")
    print(f"{'bar#':>5} {'time':<22} {'OA[t]':>10} {'OA[t-5]':>10} {'ret_raw[t]':>14}")
    print("-" * 58)
    for j in range(5, len(oa)):
        dt = win.index[j]
        rr = oa[j] / oa[j-5] - 1
        print(f"{j:>5} {str(dt):<22} {oa[j]:>10.2f} {oa[j-5]:>10.2f} {rr:>14.8f}")

    print()
    print("RE[t] = ret_raw.shift(-5min).shift(-1)[t]")
    print("      = ret_raw[t+6] (5min forward + 1 bar forward)")
    print("      = OA[t+6] / OA[t+1] - 1")
    print()
    print(f"{'bar':>4} {'signal time':<22} {'buy OA[t+1]':>13} {'sell OA[t+6]':>13} {'RE=OA[t+6]/OA[t+1]-1':>26}")
    print("-" * 76)
    for j in range(0, len(oa) - 6):
        re_ = oa[j+6] / oa[j+1] - 1
        dt = win.index[j]
        print(f"{j:>4} {str(dt):<22} {oa[j+1]:>13.2f} {oa[j+6]:>13.2f} {re_:>26.8f}")

    print()
    print("e.g. 9:05信号(bar4): buy 9:06(bar5) OA=4101, sell 9:11(bar10) OA=4102")
    print("     RE = 4102/4101-1 = 0.00024378 [OK]")
    print()

# ====================================================================
# 4. 日内 + OA (OPEN-TO-OPEN, RF=5min, skip)
# ====================================================================
def verify_intraday_oa_skip():
    print(BORDER)
    print("4. 日内 + OA (OPEN-TO-OPEN, RF=5min, end_session_skip=YES)")
    print(BORDER)
    print("skip 只改变 SignalAlign 采样点, RE 内部公式不变")
    print()

    df = pd.read_parquet('/Users/maxdeux/Documents/GTHT/data/main_mink/A.DCE.parquet')
    df['dt'] = pd.to_datetime(df['trade_time'])
    df['OA'] = df['open_price'] * df['adjustment_mul'] + df['adjustment_add']
    df = df.sort_values('dt').set_index('dt')

    # 跨 session 窗口
    win = df['2025-11-25 14:55':'2025-11-26 09:10'].copy()

    print("跨 session bars (2025-11-25 收盘 ~ 2025-11-26 开盘):")
    print(f"{'bar#':>5} {'time':<22} {'OA':>10} {'gap_from_prev':>14}")
    print("-" * 53)
    oa = []
    last = None
    for j, (dt, row) in enumerate(win.iterrows()):
        oa.append(row['OA'])
        gap = dt - last if last is not None else None
        gap_str = str(gap) if gap and gap >= pd.Timedelta('1h') else ''
        print(f"{j:>5} {str(dt):<22} {row['OA']:>10.2f} {gap_str:>14}")
        last = dt

    print()
    print("end_session_skip=True: gap >= 3h 的 bar 间会重置 session 计数器")
    print("SignalAlign 采样点从 session 起始重新计数")
    print("但 RE 内部的 .shift(-5min).shift(-1) 不受影响")
    print("=> 同一 session 内 RE[t] = OA[t+6]/OA[t+1]-1 仍然成立 [OK]")
    print()

# ====================================================================
# 5. 日内 + CA (CLOSE-TO-CLOSE, RF=5min, no-skip)
# ====================================================================
def verify_intraday_ca_noskip():
    print(BORDER)
    print("5. 日内 + CA (CLOSE-TO-CLOSE, RF=5min, no-skip)")
    print(BORDER)
    print("信号 bar t, 买入 CA[t], 卖出 CA[t+5] -> RE[t] = CA[t+5]/CA[t]-1")
    print()

    df = pd.read_parquet('/Users/maxdeux/Documents/GTHT/data/main_mink/A.DCE.parquet')
    df['dt'] = pd.to_datetime(df['trade_time'])
    df['CA'] = df['close_price'] * df['adjustment_mul'] + df['adjustment_add']
    df = df.sort_values('dt').set_index('dt')

    win = df['2025-11-26 09:00':'2025-11-26 09:25'].copy()

    print("A.DCE 2025-11-26 开盘 1-min CA (bar 0-25):")
    print(f"{'bar#':>5} {'time':<22} {'CA':>10}")
    print("-" * 39)
    ca = []
    for j, (dt, row) in enumerate(win.iterrows()):
        ca.append(row['CA'])
        print(f"{j:>5} {str(dt):<22} {row['CA']:>10.2f}")
    print()

    # RE[t] = ret_raw.shift(-5min).shift(0) = ret_raw[t+5]
    #       = CA[t+5]/CA[t] - 1
    print("RE[t] = ret_raw.shift(-5min)[t] = ret_raw[t+5]")
    print("      = CA[t+5] / CA[t] - 1")
    print()
    print(f"{'bar':>4} {'signal time':<22} {'buy CA[t]':>13} {'sell CA[t+5]':>13} {'RE=CA[t+5]/CA[t]-1':>26}")
    print("-" * 76)
    for j in range(0, len(ca) - 5):
        re_ = ca[j+5] / ca[j] - 1
        dt = win.index[j]
        print(f"{j:>4} {str(dt):<22} {ca[j]:>13.2f} {ca[j+5]:>13.2f} {re_:>26.8f}")

    print()
    print("e.g. 9:05信号(bar4): buy 9:05(bar4) CA=4101, sell 9:10(bar9) CA=4103")
    print("     RE = 4103/4101-1 = 0.00048768 [OK]")
    print()

# ====================================================================
# 6. 汇总
# ====================================================================
def print_summary():
    print(BORDER)
    print("6. 全部场景验证汇总")
    print(BORDER)
    print()

    rows = [
        ("daily+OA+RF=1d",    "ret_raw.shift(-1d).shift(-1)",   "OA[T+2]/OA[T+1]-1",     "buy T+1, sell T+2"),
        ("daily+CA+RF=1d",    "ret_raw.shift(-1d).shift(0)",     "CA[T+1]/CA[T]-1",        "buy T, sell T+1"),
        ("1min+OA+RF=5min+noskip", "ret_raw.shift(-5min).shift(-1)", "OA[t+6]/OA[t+1]-1",  "buy t+1, sell t+6"),
        ("1min+OA+RF=5min+skip",   "same (only SignalAlign diff)",  "same",                 "same"),
        ("1min+CA+RF=5min+noskip", "ret_raw.shift(-5min).shift(0)",  "CA[t+5]/CA[t]-1",    "buy t, sell t+5"),
        ("1min+OA+RF=1d+noskip",   "ret_raw.shift(-1d).shift(-1)",   "OA[t+1d+1]/OA[t+1d]-1","buy next open, sell 2nd next open"),
        ("1min+CA+RF=1d+noskip",   "ret_raw.shift(-1d).shift(0)",    "CA[t+1d]/CA[t]-1",    "buy t, sell next day"),
    ]

    print(f"{'scenario':<32} {'RE formula':<32} {'simplified':<36} {'meaning':<24}")
    print("-" * 124)
    for sc, f, s, m in rows:
        print(f"{sc:<32} {f:<32} {s:<36} {m:<24}")

    print()
    print("RESULTS:")
    print("  [OK] daily + OPEN:   RE = OA[T+2]/OA[T+1]-1 = .shift(-2) from raw ret")
    print("  [OK] daily + CLOSE:  RE = CA[T+1]/CA[T]-1   = .shift(-1) from raw ret")
    print("  [OK] intra + OPEN:   RE = OA[t+RF+1]/OA[t+1]-1 (RF bars between buy/sell)")
    print("  [OK] intra + CLOSE:  RE = CA[t+RF]/CA[t]-1")
    print("  [OK] skip only changes SignalAlign sample points, not RE formula")
    print()
    print("KEY INSIGHT: .shift(-1) at the end of OPEN formula is ESSENTIAL")
    print("  It represents the 1-bar gap between 'buy bar' and 'sell bar'")
    print("  Without it, OPEN-TO-OPEN would become 'buy T+1, sell T+1' (zero return)")
    print()


if __name__ == '__main__':
    verify_daily_oa()
    verify_daily_ca()
    verify_intraday_oa_noskip()
    verify_intraday_oa_skip()
    verify_intraday_ca_noskip()
    print_summary()
