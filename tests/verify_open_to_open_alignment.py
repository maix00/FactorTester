"""
完整的 OPEN-TO-OPEN 收益率时间对齐验证脚本

验证三种场景下 IC 测试中"下一期收益率"的时间对齐是否正确：
  1. 日度因子 (freq=1d, end_session_skip 不触发)
  2. 日内因子 (freq=1h, end_session_skip=False)
  3. 日内因子 (freq=1h, end_session_skip=True, 默认)

验证方法：对同一组品种，打印每个信号时间点对应的：
  - 当期开盘价 (today open)
  - 下期开盘价 (next period open)
  - 计算出的 RE (收益率)
  - 预期符号方向
"""

import os, sys
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import numpy as np

from tools.factors.FactorExpr import (
    FactorExpr, DataColumn, DataFreq,
    ColumnRef, ConstExpr, ShiftOp, CompositeExpr,
    signal_align,
)
from tools.factors.FactorFamily import FactorFamily, CrossSectionIC
from tools.factors.FactorTester import FactorTester
from tools.factors.Parameters import FactorNextPeriodReturns
from tools.factors.Factors import Factor

from Settings import (
    get_cat_tree, get_all_products,
    default_test_start_date, default_test_end_date,
)

# ═══════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════

def get_open_price_at_time(product, ts: pd.Timestamp, freq: str = '1h') -> float | None:
    """获取品种在指定时间点的 OA (复权开盘价)。"""
    dm = getattr(product, freq.replace('d', 'DAY').replace('h', 'MIN'))
    df = product.get_some_data(copy=False)
    if df.empty:
        return None
    if 'OA' not in df.columns:
        return None
    # 找到 ts 或 ts 之后最近的 bar
    idx = df.index.get_level_values(-1)
    mask = idx >= ts
    if not mask.any():
        return None
    row = df.loc[mask].iloc[0]
    return row.get('OA', None)


def print_separator(title: str):
    print()
    print("=" * 80)
    print(f"  {title}")
    print("=" * 80)


# ═══════════════════════════════════════════════════════════════════
# 场景 1：日度因子 (freq=1d)
# ═══════════════════════════════════════════════════════════════════

def analyze_daily():
    """日度因子：RE = (OA.delta(1d) / OA.shift(1d)).shift(-1d).shift(-1)"""
    print_separator("场景 1：日度因子 (freq=1d, OPEN_TO_OPEN)")

    # 构造 RE 表达式，直接求值验证
    OA = ColumnRef(DataColumn.OPEN_ADJUSTED)
    RF = DataFreq('1d')
    # S=0 (OPEN), 所以 RE = (OA.delta(RF)/OA.shift(RF)).shift(-RF).shift(-1)
    RE_expr = (OA.delta(RF) / OA.shift(RF)).shift(-RF).shift(-1)

    print("RE 表达式：")
    print(f"  (OA.delta(1d)/OA.shift(1d)).shift(-1d).shift(-1)")
    print()
    print("时间语义解析（日度）：")
    print("  - OA.delta(1d)        = OA(t) - OA(t-1d)       ← 当日开盘 - 前日开盘")
    print("  - OA.shift(1d)        = OA(t-1d)                ← 前日开盘")
    print("  - delta/shift          = (OA(t)-OA(t-1d))/OA(t-1d) ← 当日收益率")
    print("  - .shift(-1d)          = 把结果向前挪1天 → 位置在 t+1d")
    print("  - .shift(-1)           = 再向前挪1个bar → 位置在 t+2d (日频时就是+2天)")
    print()
    print("  ⚠  .shift(-1) 在日频下多移了一天！")
    print("  期望语义：t 日信号 → 应该对应 t+1 日的收益率")
    print("  实际结果：t 日信号 → 对应 t+2 日的收益率（多移了一天）")
    print("  公式应为：(OA.delta(RF)/OA.shift(RF)).shift(-RF) 去掉最后的 .shift(-1)")
    print()

    # 验证：手动用日线数据计算
    products = get_all_products()
    product = products[0]
    try:
        df = product.get_some_data(copy=False)
        if 'OA' not in df.columns:
            print("[SKIP] 无 OA 列")
            return

        dm = product.DAY1
        # groupby product, 取每天最后一条
        oa_daily = df.groupby(level=0).apply(
            lambda g: g['OA'].iloc[-1] if len(g) > 0 and 'OA' in g.columns else pd.NA,
            include_groups=False
        )
        if isinstance(oa_daily, pd.Series) and oa_daily.index.nlevels == 2:
            oa_daily = oa_daily.droplevel(0)

        print(f"品种：{product.name}")
        print(f"日线 OA 样本数：{len(oa_daily.dropna())}")
        print()

        # 手动算 OA_ret(t) = OA(t) / OA(t-1) - 1
        oa_ret = oa_daily / oa_daily.shift(1) - 1
        # 当前系统公式 = oa_ret.shift(-1).shift(-1) = oa_ret.shift(-2)
        system_re = oa_ret.shift(-2)
        # 正确的公式 = oa_ret.shift(-1)
        correct_re = oa_ret.shift(-1)

        # 对比某几天
        print(f"{'日期':<20} {'OA':>10} {'当日ret':>10} {'系统RE(shift-2)':>15} {'正确RE(shift-1)':>15}")
        print("-" * 72)
        for i in range(5, 12):
            ts = oa_daily.index[i]
            print(f"{str(ts)[:16]:<20} {oa_daily.iloc[i]:>10.4f} {oa_ret.iloc[i]:>10.4f} {system_re.iloc[i]:>15.4f} {correct_re.iloc[i]:>15.4f}")

    except Exception as e:
        print(f"[ERROR] {e}")


# ═══════════════════════════════════════════════════════════════════
# 场景 2：日内因子 (freq=1h, end_session_skip=False)
# ═══════════════════════════════════════════════════════════════════

def analyze_intraday_no_skip():
    """日内因子，不跳过盘间间隔"""
    print_separator("场景 2：日内因子 (freq=1h, end_session_skip=False, OPEN_TO_OPEN)")

    OA = ColumnRef(DataColumn.OPEN_ADJUSTED)
    RF = DataFreq('1d')
    RE_expr = (OA.delta(RF) / OA.shift(RF)).shift(-RF).shift(-1)

    print("RE 表达式：")
    print(f"  (OA.delta(1d)/OA.shift(1d)).shift(-1d).shift(-1)")
    print()
    print("高频语义（.shift() 按 bar 数移动，.shift(Timedelta) 按时间移动）：")
    print("  - RF = 1d → 在1h数据上等于 shift(24)     （假设每天24根1h bar）")
    print("  - .shift(-RF) = .shift(-24 bars)           ← 时间上前移24根bar")
    print("  - .shift(-1)   = .shift(-1 bar)             ← 再前移1根bar")
    print("  - 总偏移 = -25 bars = 前移1天+1小时")
    print()

    products = get_all_products()
    if not products:
        print("[SKIP] 无品种")
        return

    product = products[0]
    try:
        df = product.get_some_data(copy=False)
        if 'OA' not in df.columns:
            print("[SKIP] 无 OA 列")
            return

        dm = product.MIN1  # 1分钟数据
        freq = DataFreq('1h')
        # 需要的关键信息：每个品种每天有多少根1h bar
        day_periods = getattr(product, 'HOUR1', None)
        if day_periods is None:
            # 尝试从 MIN60 获取
            day_periods = getattr(product, 'MIN60', getattr(product, 'MIN1', None))
        if day_periods and hasattr(day_periods, 'day_periods'):
            n_bars_per_day = day_periods.day_periods
        else:
            n_bars_per_day = 24  # 默认

        print(f"品种：{product.name}, 每天约 {n_bars_per_day} 根1h bar")
        print()

        # 取几天的1h数据，打印原始 OA 和 .delta(1d), .shift(1d), .shift(-1d), .shift(-1)
        # 先重采样到1h
        oa_series = df['OA'].dropna()

        # 用最后几天可用的 1h 数据来演示
        print("时间对齐推到（1h bar）：")
        print(f"  .shift(-RF) = .shift(-1d)   = 前移 {n_bars_per_day} bars")
        print(f"  .shift(-1)                 = 前移 1 bar")
        print(f"  总偏移                     = 前移 {n_bars_per_day + 1} bars")
        print()
        print("  → 如果 t 时刻是某日收盘前最后一根1h bar（如14:00-15:00）")
        print(f"    则 RE 被推到 t+{n_bars_per_day+1} bars 后 = 次日+1h")
        print("  → 这个时间点不一定是开盘价对应的时间点")

    except Exception as e:
        print(f"[ERROR] {e}")


# ═══════════════════════════════════════════════════════════════════
# 场景 3：日内因子 (freq=1h, end_session_skip=True, 默认)
# ═══════════════════════════════════════════════════════════════════

def analyze_intraday_with_skip():
    """日内因子，跳过盘间间隔 (默认行为)"""
    print_separator("场景 3：日内因子 (freq=1h, end_session_skip=True, 默认)")

    print("SignalAlign 的 skip 行为：")
    print("  - basepoint='last'：每天取最后一根 bar 作为基准点")
    print("  - end_session_skip=True：跳过盘间间隔（如15:00→21:00之间的gap）")
    print("  - 从每天的最后一根 bar 向前按 multiple 间隔取信号点")
    print("    multiple = target_freq / source_freq = 1h / 1min = 60")
    print()
    print("  举例（1min 数据 → 1h 信号）：")
    print("    每天最后一根 bar = 15:00")
    print("    multiple = 60, 所以 skip 区域内取信号点：")
    print("      15:00 (i=base), 14:00 (i=-60), 13:00 (i=-120), ...")
    print("      跳过 15:00→21:00 的 gap")
    print("      21:00 组: 23:00 (i=base), 22:00, 21:00")
    print()
    print("  关键：每天最后一个信号点是 15:00")
    print("  所以 FE（因子值）绑定在每天 15:00")
    print("  问题：RE 的 .shift(-1d).shift(-1) 在1h频率下")
    print("    → 从15:00 前移24+1=25小时 = 次日16:00")
    print("    → 但次日的第一个信号点是 09:00（如果日盘从9点开始）或者21:00（夜盘）")
    print("    → 16:00 不在任何信号点上！")
    print()

    products = get_all_products()
    if not products:
        print("[SKIP] 无品种")
        return

    product = products[0]
    try:
        dm = getattr(product, 'MIN1', None)
        if dm is None:
            print("[SKIP] 无 MIN1 DataMeta")
            return

        day_periods = dm.day_periods if hasattr(dm, 'day_periods') else 1440
        print(f"品种：{product.name}, MIN1 day_periods = {day_periods}")
        print()

        # 1h信号: multiple = 60
        multiple = 60
        print(f"1h 信号：multiple = {multiple} bars")
        print()
        print("skip 行为下信号点分布（1min → 1h）：")
        print("  日盘(09:00-15:00): 09:00, 10:00, 11:00, 13:30, 14:30, 15:00")
        print("  夜盘(21:00-23:00): 21:00, 22:00, 23:00 (假设夜盘到23:00)")
        print()
        print("  每天最后一个信号点 = 15:00（日盘收盘）")
        print("  FE 在 15:00 取值 → IC 检验相关性")
        print()
        print("  RE = (OA.delta(1d)/OA.shift(1d)).shift(-1d).shift(-1)")
        print("    OA.delta(1d)    = 当日开盘 - 前日开盘")
        print("    OA.shift(1d)    = 前日开盘")
        print("    .shift(-1d)     = 前移24h → 位置=次日某bar")
        print("    .shift(-1)      = 前移1h  → 位置=次日某bar+1h")
        print()
        print("  问题: .shift(-1) 在 OPEN_TO_OPEN 场景下,")
        print("  目的是把 RE 从 first 位置挪到与 FE 对齐的 last 位置")
        print("  但 .shift(-1) 是 bar 级偏移,不是按信号时间点对齐")
        print("  在1h 信号频率下,这可能导致 RE 和 FE 不在同一信号层级")

    except Exception as e:
        print(f"[ERROR] {e}")


# ═══════════════════════════════════════════════════════════════════
# 场景 4：实际运行 CrossSectionIC 并提取中间结果
# ═══════════════════════════════════════════════════════════════════

def run_live_ic_and_show_alignment(freq_str: str, label: str):
    """用真实数据运行一次 CrossSectionIC，打印 FE/RE 对齐详情。"""
    print_separator(f"场景：{label} (freq={freq_str})")

    try:
        products = get_all_products()
        if not products:
            print("[SKIP] 无品种")
            return

        tester = FactorTester(
            products=list(products)[:3],  # 只取前3个品种加快速度
            time_range=(default_test_start_date, default_test_end_date),
        )

        # 用 MmRet 作为被测因子 (最简单的动量因子)
        from tools.factors.FactorFamily import FactorFamily
        import importlib

        # 动态加载 MmRet
        spec = importlib.util.spec_from_file_location(
            "MmRet", os.path.join(os.path.dirname(__file__), "Factors", "MmRet.py")
        )
        mm_ret_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mm_ret_mod)

        from tools.factors.Parameters import FactorFreqParam, ReturnFreqParam
        freq_param = FactorFreqParam
        return_freq_param = ReturnFreqParam

        # 构造 CrossSectionIC
        ic_family = CrossSectionIC()

        # 用 MmRet 的 FE
        from Factors.MmRet import MmRet as MmRetFamily
        mm_family = MmRetFamily()

        FactorFreqParam.set_value(DataFreq(freq_str))
        params_dict = {'F': DataFreq(freq_str)}
        all_factors = mm_family.get_factors(params_list=params_dict)
        if not all_factors:
            print("[SKIP] 无法获取因子")
            return

        factor = all_factors[0]
        factor.evaluate(tester.products, source_freq=factor._source_freq)

        # 获取 FE 的 source_table
        fe_table = factor.source_table if hasattr(factor, 'source_table') else factor._source_data
        if fe_table is None:
            print("[SKIP] FE 无数据")
            return

        print(f"FE source_table shape: {fe_table.shape}")
        print(f"FE source_table index names: {fe_table.index.names}")
        print(f"FE source_table 前5行:")
        print(fe_table.head(5))
        print()

        # 运行 IC
        SC = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED
        shift = 0  # OPEN → shift=0
        RF = DataFreq(freq_str)

        ic_factor = ic_family.get_factor(
            FE=factor,
            SC=SC.value,
            RF=RF.value,
            S=shift,
            Lag=0,
            F=RF.value,
        )
        ic_factor.clear()
        ic_factor.evaluate(tester.products, source_freq=factor._source_freq)

        ic_series = ic_factor.table.get("IC", pd.Series(dtype=float))
        re_table = ic_factor.get_intermediate("RE")

        print(f"IC series length: {len(ic_series.dropna())}")
        print(f"IC 均值: {ic_series.mean():.4f}")
        print()

        if re_table is not None and not re_table.empty:
            print(f"RE table shape: {re_table.shape}")
            print(f"RE table index names: {re_table.index.names}")
            print(f"RE 样本（前10行）：")
            print(re_table.head(10))
            print()
            print("RE 描述统计：")
            print(re_table.describe())

            # 检查 RE 是否全是 NaN → 对齐失败
            nan_pct = re_table.isna().sum().sum() / re_table.size * 100
            print(f"RE NaN 比例: {nan_pct:.1f}%")
            if nan_pct > 90:
                print("  ⚠ RE 几乎全是 NaN！时间对齐可能存在问题")

    except Exception as e:
        import traceback
        print(f"[ERROR] {e}")
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print_separator("OPEN-TO-OPEN 下一期收益率时间对齐分析")
    print()
    print("核心公式 (CrossSectionIC.factor_expr()):")
    print("  RE = (SC.delta(RF) / SC.shift(RF)).shift(-RF).shift(S - 1)")
    print("  SC=OPEN_ADJUSTED, S=0  →  RE = (OA.delta(RF)/OA.shift(RF)).shift(-RF).shift(-1)")
    print()
    print("  .shift(-1) 的来源：当 SC=OPEN 时 S=0，shift(S-1) = shift(-1)")
    print("  这个 .shift(-1) 的意图是把 RE 从 'first' 位置挪到 'last' 位置与 FE 对齐")
    print("  但 .shift() 在不同频率下行为不同：")
    print("    日频：shift(-1) = 前移 1 天")
    print("    1h频：shift(-1) = 前移 1 根 bar (1小时)")
    print()

    # 运行分析
    analyze_daily()
    analyze_intraday_no_skip()
    analyze_intraday_with_skip()

    # 尝试用真实 CrossSectionIC 跑一下（如果加载成功）
    print()
    print_separator("实际 IC 运行验证")
    try:
        run_live_ic_and_show_alignment('1d', '日度因子')
    except Exception as e:
        print(f"日度 IC 运行跳过: {e}")

    try:
        run_live_ic_and_show_alignment('1h', '日内因子 (1h)')
    except Exception as e:
        print(f"1h IC 运行跳过: {e}")
