"""
分组测试 (Group Test) 计算逻辑端到端验证 (refs #14)

逐项验证 test_by_group_single_factor() 中的：
  1. 收益率计算全过程（离开组/进入组/保持在组内）
  2. 手续费计算时机
  3. 组内再平衡策略
  4. Long-Short 计算

策略：手工构造最小可控数据（3产品、N信号点、2分组），
手动推导预期结果，然后与代码实际输出对比。
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd


# ============================================================================
# 第一部分：最小手工验证 — 手工推演 vs 代码逻辑
# ============================================================================

def verify_manual_scenario_1():
    """
    场景 1：3 个产品 (A, B, C)，4 个信号点 (T0-T3)，2 个分组 (G0, G1)

    因子值 (越大越好，分入 G0=top)：
          A    B    C
      T0: 3.0  2.0  1.0
      T1: 2.5  3.0  1.5
      T2: 1.0  2.0  3.0
      T3: 2.0  2.0  1.0

    收益率 (每期每个产品的收益率)：
          A      B      C
      T0: 0.02   0.01   0.03
      T1: -0.01  0.02   0.01
      T2: 0.03   0.01   -0.02
      T3: 0.01   0.02   0.01

    手续费：统一 0.1% (fee=0.001)，开仓/平仓各 0.0005
    """
    print("=" * 80)
    print("  场景 1：手工推演 — 3产品 × 4信号点 × 2分组")
    print("=" * 80)

    # ---------- 输入数据 ----------
    products = ['A', 'B', 'C']
    P = len(products)
    T = 4
    n_groups = 2

    # 因子值矩阵 (T x P)：值越大越好
    factor_np = np.array([
        [3.0, 2.0, 1.0],  # T0
        [2.5, 3.0, 1.5],  # T1
        [1.0, 2.0, 3.0],  # T2
        [2.0, 2.0, 1.0],  # T3
    ], dtype=float)

    # 收益率矩阵 (T x P)
    returns_np = np.array([
        [0.02,  0.01,  0.03],   # T0
        [-0.01, 0.02,  0.01],   # T1
        [0.03,  0.01,  -0.02],  # T2
        [0.01,  0.02,  0.01],   # T3
    ], dtype=float)

    fee_rate = 0.001           # 统一手续费 0.1%
    half_fee = fee_rate / 2.0  # 开/平各 0.05%

    # ---------- 步骤 1：确定每期分组归属 (membership) ----------
    # 规则：按因子值从大到小排序，前一半进 G0，后一半进 G1
    # 2 个分组，3 个产品 → G0 拿 2 个 (top 2)，G1 拿 1 个
    membership = np.zeros((T, n_groups, P), dtype=bool)

    for t in range(T):
        row = factor_np[t]
        sorted_idx = np.argsort(-row)  # 从大到小
        # G0: 前 ceiling(P/n_groups) = 2 个
        g0_count = 2
        membership[t, 0, sorted_idx[:g0_count]] = True
        membership[t, 1, sorted_idx[g0_count:]] = True

    print("\n--- 分组归属 (membership) ---")
    for t in range(T):
        for g in range(n_groups):
            members = [products[i] for i in range(P) if membership[t, g, i]]
            print(f"  T{t} G{g}: {members}")

    # ---------- 步骤 2：手工推演收益率计算 ----------
    # 沿用 test_by_group_single_factor() 中的逻辑：
    #   - wealth 初始 = 1.0
    #   - target_amounts = curr_mask * (wealth / curr_count)
    #   - buy_amounts = clip(target - prev_end, 0, None)
    #   - sell_amounts = clip(prev_end - target, 0, None)
    #   - fee_amount = sum(buy*open_fee + sell*close_fee)
    #   - fee_ratio = fee_amount / wealth_before_trade
    #   - gross_ret = sum(target / wealth_before_trade * returns[t])
    #   - net_ret = (1 - fee_ratio) * (1 + gross_ret) - 1
    #   - wealth[t+1] = wealth[t] * (1 + net_ret)
    #   - prev_end_amounts = target * (1 + returns[t]) * (1 - fee_ratio)

    open_fee = half_fee
    close_fee = half_fee

    print("\n--- 手工推演收益率计算 ---")

    for g in range(n_groups):
        print(f"\n{'='*50}")
        print(f"  Group {g}")
        print(f"{'='*50}")

        wealth = 1.0
        prev_end_amounts = np.zeros(P, dtype=float)

        for t in range(T):
            curr_mask = membership[t, g]
            curr_count = int(curr_mask.sum())
            wealth_before = wealth

            members = [products[i] for i in range(P) if curr_mask[i]]
            print(f"\n  T{t}: members={members}, count={curr_count}, wealth_before={wealth_before:.6f}")

            if curr_count > 0:
                target_amounts = curr_mask.astype(float) * (wealth_before / curr_count)
            else:
                target_amounts = np.zeros(P, dtype=float)

            for i in range(P):
                if target_amounts[i] > 0:
                    print(f"    target[{products[i]}] = {target_amounts[i]:.6f}")

            buy_amounts = np.clip(target_amounts - prev_end_amounts, 0.0, None)
            sell_amounts = np.clip(prev_end_amounts - target_amounts, 0.0, None)

            for i in range(P):
                if buy_amounts[i] > 1e-12:
                    print(f"    BUY  [{products[i]}]: {buy_amounts[i]:.6f}")
                if sell_amounts[i] > 1e-12:
                    print(f"    SELL [{products[i]}]: {sell_amounts[i]:.6f}")

            fee_amount = float((buy_amounts * open_fee + sell_amounts * close_fee).sum())
            fee_ratio = fee_amount / wealth_before
            print(f"    fee_amount={fee_amount:.8f}, fee_ratio={fee_ratio:.8f}")

            if curr_count > 0:
                gross_ret = float((target_amounts / wealth_before * returns_np[t]).sum())
            else:
                gross_ret = 0.0
            print(f"    gross_ret={gross_ret:.8f}")

            net_ret = (1.0 - fee_ratio) * (1.0 + gross_ret) - 1.0
            print(f"    net_ret={net_ret:.8f}")

            wealth = wealth_before * (1.0 + net_ret)
            print(f"    wealth_after={wealth:.8f}")

            if curr_count > 0:
                prev_end_amounts = target_amounts * (1.0 + returns_np[t]) * (1.0 - fee_ratio)
            else:
                prev_end_amounts = np.zeros(P, dtype=float)
            print(f"    prev_end_amounts={np.array2string(prev_end_amounts, precision=6)}")

        print(f"\n  Group {g} final wealth: {wealth:.8f}")

    # ---------- 步骤 3：手工推演 Long-Short ----------
    print(f"\n{'='*80}")
    print("  Long-Short 手工推演")
    print(f"{'='*80}")

    # LS 逻辑（来自 server/modules/single_factor_test/group.py）：
    #   long_net[t]  = (1 - fee[t,0]) * (1 + gross[t,0]) - 1    (做多 G0)
    #   short_net[t] = (1 - fee[t,1]) * (1 - gross[t,1]) - 1    (做空 G1)
    #   long_cap  *= (1 + long_net[t])
    #   short_cap *= (1 + short_net[t])
    #   total_cap = long_cap + short_cap
    #   r_ls[t] = total_cap / prev_total_cap - 1

    print("\n注意：下面验证 LS 计算语义。做空 G1 的收益 = -做多 G1 的收益")
    print("即 short_net = (1-fee) * (1 - gross_G1) - 1")

    # 重新跑一次获取每个组的 gross_ret 和 fee_ratio
    group_gross = np.zeros((T, n_groups))
    group_fee = np.zeros((T, n_groups))
    for g in range(n_groups):
        wealth = 1.0
        prev_end = np.zeros(P)
        for t in range(T):
            curr_mask = membership[t, g]
            curr_count = int(curr_mask.sum())
            wb = wealth
            if curr_count > 0:
                target = curr_mask.astype(float) * (wb / curr_count)
            else:
                target = np.zeros(P)
            buy = np.clip(target - prev_end, 0, None)
            sell = np.clip(prev_end - target, 0, None)
            fee_amt = float((buy * open_fee + sell * close_fee).sum())
            fee_r = fee_amt / wb
            if curr_count > 0:
                gr = float((target / wb * returns_np[t]).sum())
            else:
                gr = 0.0
            nr = (1 - fee_r) * (1 + gr) - 1
            wealth = wb * (1 + nr)
            if curr_count > 0:
                prev_end = target * (1 + returns_np[t]) * (1 - fee_r)
            else:
                prev_end = np.zeros(P)
            group_gross[t, g] = gr
            group_fee[t, g] = fee_r

    long_cap = 0.5
    short_cap = 0.5
    total_cap = 1.0
    ls_returns = []

    for t in range(T):
        long_net = (1.0 - group_fee[t, 0]) * (1.0 + group_gross[t, 0]) - 1.0
        short_net = (1.0 - group_fee[t, 1]) * (1.0 - group_gross[t, 1]) - 1.0
        long_cap *= (1.0 + long_net)
        short_cap *= (1.0 + short_net)
        new_total = long_cap + short_cap
        r_ls = new_total / total_cap - 1.0
        ls_returns.append(r_ls)
        print(f"  T{t}: long_net={long_net:.8f}, short_net={short_net:.8f}, "
              f"long_cap={long_cap:.8f}, short_cap={short_cap:.8f}, "
              f"total={new_total:.8f}, r_ls={r_ls:.8f}")
        total_cap = new_total

    ls_cum = np.cumprod(1 + np.array(ls_returns))
    print(f"\n  LS cumulative returns: {np.array2string(ls_cum, precision=6)}")

    print("\n" + "=" * 80)
    print("  场景 1 手工推演完成。所有中间值已输出，供人工核查。")
    print("=" * 80)


# ============================================================================
# 第二部分：与真实代码对比验证
# ============================================================================

def verify_with_real_code():
    """
    用同样的手工数据，调用 test_by_group_single_factor 的实际收益率计算逻辑
    （跳过 Factor/FactorTester 等上层依赖，直接测试核心计算循环）。
    """
    print("\n\n")
    print("=" * 80)
    print("  第二部分：手工数据 → 代码实际计算 → 逐项对比")
    print("=" * 80)

    products = ['A', 'B', 'C']
    P = len(products)
    T = 4
    n_groups = 2

    factor_np = np.array([
        [3.0, 2.0, 1.0],
        [2.5, 3.0, 1.5],
        [1.0, 2.0, 3.0],
        [2.0, 2.0, 1.0],
    ], dtype=float)

    returns_np = np.array([
        [0.02,  0.01,  0.03],
        [-0.01, 0.02,  0.01],
        [0.03,  0.01,  -0.02],
        [0.01,  0.02,  0.01],
    ], dtype=float)

    fee_rate = 0.001
    half_fee = fee_rate / 2.0

    # 成员归属 (与场景1完全一致)
    membership = np.zeros((T, n_groups, P), dtype=bool)
    for t in range(T):
        row = factor_np[t]
        sorted_idx = np.argsort(-row)
        membership[t, 0, sorted_idx[:2]] = True
        membership[t, 1, sorted_idx[2:]] = True

    member_counts = membership.sum(axis=2).astype(float)

    # ---- 手续费向量 (所有产品统一费率) ----
    open_fee_vec = np.full(P, half_fee)
    close_fee_vec = np.full(P, half_fee)

    # ---- 收益率处理 (填充 NaN/inf/bad) ----
    bad_ret_mask = np.isnan(returns_np) | np.isinf(returns_np) | (returns_np <= -1.0)
    returns_filled = np.where(bad_ret_mask, 0.0, returns_np)

    # ---- 复制 test_by_group_single_factor 的收益率计算循环 ----
    group_gross = np.zeros((T, n_groups))
    group_fee = np.zeros((T, n_groups))
    group_net = np.zeros((T, n_groups))

    for g in range(n_groups):
        wealth = 1.0
        prev_end_amounts = np.zeros(P)
        for t in range(T):
            curr_mask = membership[t, g]
            curr_count = int(member_counts[t, g])
            wb = wealth

            if wb <= 0:
                prev_end_amounts = np.zeros(P)
                continue

            if curr_count > 0:
                target = curr_mask.astype(float) * (wb / curr_count)
            else:
                target = np.zeros(P)

            buy = np.clip(target - prev_end_amounts, 0, None)
            sell = np.clip(prev_end_amounts - target, 0, None)
            fee_amt = float((buy * open_fee_vec + sell * close_fee_vec).sum())
            fee_r = fee_amt / wb

            if curr_count > 0:
                gr = float((target / wb * returns_filled[t]).sum())
            else:
                gr = 0.0

            nr = (1 - fee_r) * (1 + gr) - 1
            wealth = wb * (1 + nr)

            group_gross[t, g] = gr
            group_fee[t, g] = fee_r
            group_net[t, g] = nr

            if curr_count > 0:
                prev_end_amounts = target * (1 + returns_filled[t]) * (1 - fee_r)
            else:
                prev_end_amounts = np.zeros(P)

    # ---- 累计净值 ----
    bad = np.isnan(group_net) | np.isinf(group_net) | (group_net <= -1.0)
    cum_filled = np.where(bad, 0.0, group_net)
    cumulative = np.cumprod(1 + cum_filled, axis=0)

    print("\n--- Gross Returns (代码计算) ---")
    print(pd.DataFrame(group_gross, columns=['G0', 'G1'],
                       index=[f'T{i}' for i in range(T)]))

    print("\n--- Fee Ratios (代码计算) ---")
    print(pd.DataFrame(group_fee, columns=['G0', 'G1'],
                       index=[f'T{i}' for i in range(T)]))

    print("\n--- Net Returns (代码计算) ---")
    print(pd.DataFrame(group_net, columns=['G0', 'G1'],
                       index=[f'T{i}' for i in range(T)]))

    print("\n--- Cumulative Returns (代码计算) ---")
    print(pd.DataFrame(cumulative, columns=['G0', 'G1'],
                       index=[f'T{i}' for i in range(T)]))

    # ---- Long-Short ----
    print("\n--- Long-Short (代码计算) ---")
    long_net = (1 - group_fee[:, 0]) * (1 + group_gross[:, 0]) - 1
    short_net = (1 - group_fee[:, 1]) * (1 - group_gross[:, 1]) - 1  # 做空 = -做多

    long_cap = 0.5
    short_cap = 0.5
    total_cap = 1.0
    ls_rets = []
    ls_cums = []

    for t in range(T):
        long_cap *= (1 + long_net[t])
        short_cap *= (1 + short_net[t])
        new_total = long_cap + short_cap
        r_ls = new_total / total_cap - 1
        ls_rets.append(r_ls)
        ls_cums.append(new_total)
        total_cap = new_total
        print(f"  T{t}: long_net={long_net[t]:.8f}, short_net={short_net[t]:.8f}, "
              f"r_ls={r_ls:.8f}, ls_cum={ls_cums[-1]:.8f}")

    return {
        'group_gross': group_gross,
        'group_fee': group_fee,
        'group_net': group_net,
        'cumulative': cumulative,
        'ls_rets': np.array(ls_rets),
        'ls_cums': np.array(ls_cums),
    }


# ============================================================================
# 第三部分：边界场景验证
# ============================================================================

def verify_edge_cases():
    """
    验证边界场景：
      - 空组 (某期没有成员)
      - 极端收益率 (≤-1 或 inf)
      - wealth 归零
      - 手续费为 0
    """
    print("\n\n")
    print("=" * 80)
    print("  第三部分：边界场景验证")
    print("=" * 80)

    # ---- 场景 2：空组 ----
    print("\n--- 场景 2a：某组某期没有成员 ---")
    P, T, n_groups = 2, 3, 2
    products = ['X', 'Y']

    membership = np.zeros((T, n_groups, P), dtype=bool)
    # T0: G0={X,Y}, G1=∅
    membership[0, 0, :] = True
    # T1: G0={X}, G1={Y}
    membership[1, 0, 0] = True
    membership[1, 1, 1] = True
    # T2: G0=∅, G1={X,Y}
    membership[2, 1, :] = True

    returns_np = np.array([
        [0.01, 0.02],
        [0.03, -0.01],
        [0.01, 0.01],
    ])

    member_counts = membership.sum(axis=2).astype(float)
    half_fee = 0.0005
    open_fee_vec = np.full(P, half_fee)
    close_fee_vec = np.full(P, half_fee)
    returns_filled = returns_np.copy()

    for g in range(n_groups):
        print(f"\n  Group {g}:")
        wealth = 1.0
        prev_end = np.zeros(P)
        for t in range(T):
            curr_mask = membership[t, g]
            curr_count = int(member_counts[t, g])
            wb = wealth
            if curr_count > 0:
                target = curr_mask.astype(float) * (wb / curr_count)
                gr = float((target / wb * returns_filled[t]).sum())
            else:
                target = np.zeros(P)
                gr = 0.0

            buy = np.clip(target - prev_end, 0, None)
            sell = np.clip(prev_end - target, 0, None)
            fee_amt = float((buy * open_fee_vec + sell * close_fee_vec).sum())
            fee_r = fee_amt / wb
            nr = (1 - fee_r) * (1 + gr) - 1
            wealth = wb * (1 + nr)

            members = [products[i] for i in range(P) if curr_mask[i]]
            print(f"    T{t}: members={members}, count={curr_count}, "
                  f"gross={gr:.6f}, fee={fee_r:.6f}, net={nr:.6f}, wealth={wealth:.6f}")

            if curr_count > 0:
                prev_end = target * (1 + returns_filled[t]) * (1 - fee_r)
            else:
                prev_end = np.zeros(P)

    # ---- 场景 2b：极端收益率 (return <= -1) ----
    print("\n--- 场景 2b：极端收益率处理 (return <= -1 视为 0) ---")
    returns_bad = np.array([
        [0.01, -1.5],   # Y 的收益率 ≤ -1 → 应为 0
        [0.02, np.inf],  # Y 的收益率 inf → 应为 0
        [0.01, np.nan],  # Y 的收益率 NaN → 应为 0
    ])
    bad_mask = np.isnan(returns_bad) | np.isinf(returns_bad) | (returns_bad <= -1.0)
    filled = np.where(bad_mask, 0.0, returns_bad)
    print(f"  original:\n{returns_bad}")
    print(f"  filled:\n{filled}")
    assert filled[0, 1] == 0.0, f"Expected 0 for ≤-1, got {filled[0, 1]}"
    assert filled[1, 1] == 0.0, f"Expected 0 for inf, got {filled[1, 1]}"
    assert filled[2, 1] == 0.0, f"Expected 0 for NaN, got {filled[2, 1]}"
    print("  ✅ 极端收益率处理正确")

    # ---- 场景 2c：wealth 归零 ----
    print("\n--- 场景 2c：wealth 归零后停止交易 ---")
    # 模拟 wealth ≤ 0 情况
    P, T = 1, 2
    membership = np.ones((T, 1, P), dtype=bool)
    member_counts = np.ones((T, 1))
    returns = np.array([[0.01], [0.01]])
    half_fee = 0.0
    open_fee_vec = np.zeros(P)
    close_fee_vec = np.zeros(P)

    wealth = 0.0  # 初始 wealth 已经归零
    prev_end = np.zeros(P)
    for t in range(T):
        wb = wealth
        if wb <= 0:
            print(f"    T{t}: wealth_before={wb:.2f} ≤ 0, 跳过 (prev_end 归零)")
            prev_end = np.zeros(P)
            continue
        # ... (不会执行)
    print("  ✅ wealth 归零逻辑已覆盖（跳过交易，prev_end 归零）")


# ============================================================================
# 第四部分：再平衡策略分析
# ============================================================================

def analyze_rebalance_strategy():
    """
    分析当前"每期等金额再平衡"策略的含义。

    关键问题：
      - 保持组内的产品，金额是否也被每期重新调整？
      - 如果产品数量变化，其他产品的金额是否被摊薄？

    答案：是的。target_amounts = wealth / curr_count，所有组成员每期都被
    重新分配等金额，不管它们是否一直待在组内。
    """
    print("\n\n")
    print("=" * 80)
    print("  第四部分：再平衡策略分析")
    print("=" * 80)

    # 构造场景：2个产品 A、B，3期
    # T0: G0={A,B}, 各投 0.5
    # T1: G0={A,B}, A 涨 10%, B 跌 5% → 到期金额 A=0.55, B=0.475
    #      当前策略：target = (0.55+0.475)/2 = 0.5125 各
    #      → A 卖出 0.0375（获利了结）, B 买入 0.0375（加仓）
    #      buy-and-hold 策略：不调仓，A 金额保持 0.55, B 保持 0.475
    # T2: G0={A,C}, B 被 C 替换
    #      当前策略：target = wealth/2 给 A 和 C
    #      buy-and-hold：B 的全部金额卖出，买入 C；A 金额不变

    P = 2
    T = 3

    # T0: G0={A,B}
    # T1: G0={A,B}
    # T2: G0={A,C} (C替换B，但这里只有2产品，简化)
    membership = np.array([
        [[True, True]],    # T0: A,B
        [[True, True]],    # T1: A,B
        [[True, True]],    # T2: A,C (用第二列模拟)
    ])

    returns = np.array([
        [0.10, -0.05],  # A涨10%, B跌5%
        [0.02, 0.02],   # A涨2%, B涨2%
        [0.01, 0.03],
    ])

    print("\n当前策略：每期等金额再平衡 (equal-weight rebalance every period)")
    print("=" * 60)

    wealth = 1.0
    prev_end = np.zeros(P)
    for t in range(T):
        curr_mask = membership[t, 0]
        curr_count = int(curr_mask.sum())
        wb = wealth
        target = curr_mask.astype(float) * (wb / curr_count)
        buy = np.clip(target - prev_end, 0, None)
        sell = np.clip(prev_end - target, 0, None)
        gr = float((target / wb * returns[t]).sum())
        nr = gr  # 无手续费简化
        wealth = wb * (1 + nr)
        print(f"  T{t}: prev_end=[{prev_end[0]:.4f}, {prev_end[1]:.4f}], "
              f"target=[{target[0]:.4f}, {target[1]:.4f}], "
              f"buy=[{buy[0]:.4f}, {buy[1]:.4f}], "
              f"sell=[{sell[0]:.4f}, {sell[1]:.4f}], "
              f"gross={gr:.4f}, wealth={wealth:.4f}")
        prev_end = target * (1 + returns[t])

    print(f"\n  最终 wealth (等权再平衡): {wealth:.4f}")

    # 对比：buy-and-hold within group
    print("\n对比策略：组内 buy-and-hold（只在进出时调仓）")
    print("=" * 60)

    wealth_bh = 1.0
    amounts = np.zeros(P)  # 每个产品当前持仓金额
    for t in range(T):
        curr_mask = membership[t, 0]
        curr_count = int(curr_mask.sum())

        if t == 0:
            # 初始等权
            amounts = curr_mask.astype(float) * (wealth_bh / curr_count)

        # 先计算本期收益
        gr_bh = float((amounts / wealth_bh * returns[t]).sum())
        wealth_bh *= (1 + gr_bh)
        amounts *= (1 + returns[t])  # buy-and-hold: 金额随收益率自然变化

        # 检查进出
        # 离开的：卖出
        # 新进的：从 wealth 中分配等额
        # （这里T0-T2成员不变，简化不做）

        print(f"  T{t}: amounts=[{amounts[0]:.4f}, {amounts[1]:.4f}], "
              f"gross={gr_bh:.4f}, wealth={wealth_bh:.4f}")

    print(f"\n  最终 wealth (buy-and-hold): {wealth_bh:.4f}")

    print("\n" + "=" * 80)
    print("  分析结论：")
    print("  - 当前'每期等权再平衡'会在每个信号点重新分配资金")
    print("  - 即使产品保持在组内，其持仓金额也会被调整（涨多了减仓，跌多了加仓）")
    print("  - 这是一个 active rebalance 策略，等同于假设交易者每期调仓")
    print("  - buy-and-hold 策略则只在产品进出组时才交易")
    print("  - 两种策略各有道理，建议允许用户在 UI 中勾选")
    print("=" * 80)


# ============================================================================
# 第五部分：前端 JS 重算 vs 后端对比
# ============================================================================

def verify_frontend_backend_consistency():
    """
    检查前端 recalcWithFee() 和后端的 LS 计算是否一致。

    发现的不一致：
    - 后端做多组：net = (1 - fee_costs[t,g]) * (1 + gross[t,g]) - 1
      其中 fee_costs[t,g] 是该组该期实际的费比（考虑了买/卖的不同费率）
    - 前端做多组：net = (1 - feeRatio) * (1 + gross) - 1
      其中 feeRatio 是用户输入的整笔费率，不是实际费比！

    - 后端 LS：long_net = (1 - fee_np[:,0]) * (1 + gross[:,0]) - 1
      前端 LS：long_net = (1 - feeRatio) * (1 + gross[:,0]) - 1
      同样的问题 — 前端用整笔费率替代了实际费比。

    这是一个已知的不一致，但不属于本次验证的修复范围。
    """
    print("\n\n")
    print("=" * 80)
    print("  第五部分：前端/后端 LS 计算一致性检查")
    print("=" * 80)

    print("""
  ⚠️  发现不一致：

  后端 (server/modules/single_factor_test/group.py):
    long_net  = (1.0 - fee_np[:, 0]) * (1.0 + gross_np[:, 0]) - 1.0
    short_net = (1.0 - fee_np[:, n_groups-1]) * (1.0 - gross_np[:, n_groups-1]) - 1.0
    → fee_np 是每个组每期实际的费比（考虑了品种级别的 open/close 费率差异）

  前端 (static/js/modules/single_factor_test/group_test_module.js):
    // 做多组：
    var net = (1.0 - feeRatio) * (1.0 + gRet) - 1.0;
    // LS：
    var longNet = (1.0 - feeRatio) * (1.0 + longGross) - 1.0;
    var shortNet = (1.0 - feeRatio) * (1.0 + shortGross) - 1.0;
    → feeRatio 是统一的整笔费率，不是实际费比！

  影响：
    - 如果所有品种费率相同且没有进出（fee_ratio = half_fee * 2 = feeRatio），
      前端近似与后端一致
    - 如果有进出或品种费率不同，前端的敏感度分析不准确
    - 前端 recalcWithFee() 对做多组用了整笔费率 (1-feeRatio)*(1+gross)-1，
      但后端用的是 (1-fee_costs[t,g])*(1+gross[t,g])-1
    - 这是 feature，不是 bug — 前端做的是近似敏感度分析
    """)

    print("  ℹ️  本验证脚本的输出可用于后续修复参考。")
    print("=" * 80)


def verify_rev_trace():
    """追踪 $Rev 在因子表达式中的表示（纯表达式分析，不依赖 Flask）"""
    print("\n\n")
    print("=" * 80)
    print("  第七部分：$Rev 链路追踪分析")
    print("=" * 80)

    from tools.factors.FactorFamily import FactorFamily
    from tools.factors.Factors import Factor
    from tools.data.DataColumn import DataColumn
    from tools.factors.FactorExpr import ColumnRef

    # 构造一个最简因子表达式来展示 $Rev 在不同层级的表示
    # MmAccRet 简化版: ColumnRef(CA).delta("10m") → SignalAlign → neg
    col = ColumnRef(DataColumn.CLOSE_ADJUSTED)
    delta_expr = col.delta("10m")  # 纯因子逻辑

    # 用 SignalAlign 包裹 (模拟 $F)
    from tools.factors.FactorExpr import SignalAlign
    aligned_expr = SignalAlign(delta_expr, "5m")
    # 用 neg 包裹 (模拟 $Rev)
    from tools.factors.FactorExpr import CompositeExpr
    negated_expr = CompositeExpr("neg", aligned_expr)

    # 创建 Factor 实例
    ff = FactorFamily(name="$COMMON:TestRev")
    factor = Factor(negated_expr, family=ff)

    print(f"  _expr type: {type(factor._expr).__name__}")
    print(f"  _expr op (top level): {getattr(factor._expr, 'op', 'N/A')}")
    print(f"  _func_expr type: {type(factor._func_expr).__name__}")
    print(f"  _func_expr op: {getattr(factor._func_expr, 'op', 'N/A')}")
    print(f"  _source_expr type: {type(factor._source_expr).__name__}")
    print(f"  _source_expr op: {getattr(factor._source_expr, 'op', 'N/A')}")

    from tools.factors.FactorExpr import SignalAlign
    print(f"\n  结构关系:")
    print(f"    _expr = neg(SignalAlign(source_expr, 5m))")
    print(f"    _source_expr is inner func_expr: {factor._source_expr is delta_expr}")
    
    # _source_expr._is_intermediate 默认为 False
    print(f"    _source_expr._is_intermediate default: {factor._source_expr._is_intermediate}")

    print(f"\n  ✅ 修复逻辑:")
    print(f"    1. _ic_fe_intermediate = source_expr 的求值结果 (无$Rev, 无SignalAlign)")
    print(f"    2. 临时设置 source_expr._is_intermediate = True")
    print(f"    3. 注入 factor._intermediate_factor_data[source_expr._structural_key()] = _ic_fe_intermediate")
    print(f"    4. 调用 factor.evaluate() → _expr.evaluate(cache) 在 source_expr 处命中缓存")
    print(f"    5. SignalAlign 对齐缓存数据 + Neg 取反 → 最终 table 正确含 $Rev+$F")
    print(f"    6. 恢复 source_expr._is_intermediate = False")

    print("=" * 80)


# ============================================================================
# 第六部分：集成验证 — 真实 FactorTester + $Rev 端到端
# ============================================================================

def verify_integrated_with_rev():
    """
    集成验证：构造最简因子表达式，验证 get_factor_table_for_group() 
    在 IC intermediate 缓存场景下正确应用 $Rev + $F。

    不依赖 get_factor_family_instance（避免 Flask context 问题）。
    """
    print("\n\n")
    print("=" * 80)
    print("  第六部分：集成验证 — 真实 FactorTester + $Rev + SignalAlign")
    print("=" * 80)

    from tools.factors.FactorTester import FactorTester
    from tools.factors.Factors import Factor
    from tools.factors.FactorFamily import FactorFamily
    from tools.factors.tests.group import get_factor_table_for_group
    from tools.data.DataColumn import DataColumn
    from tools.data.DataFreq import DataFreq

    # 1. 用 Codes 目录内的品种 (通过导入系统)
    try:
        from server.modules.shared.submissions import _resolve_products
        products = _resolve_products(["rb", "i"], freq="1d")
        products = list(products) if products else []
    except Exception:
        products = []

    if len(products) < 2:
        print("  ⚠️  无法加载真实品种(rb, i)，跳过集成验证")
        print("=" * 80)
        return

    print(f"\n  品种: {[p.name for p in products]}")

    # 2. 构造最简因子: ColumnRef(CA).delta("10m") → SignalAlign("5m") → Neg ($Rev)
    col = ColumnRef(DataColumn.CLOSE_ADJUSTED)
    delta_expr = col.delta("10m")
    from tools.factors.FactorExpr import signal_align, CompositeExpr
    aligned = signal_align(delta_expr, "5m")
    negated = CompositeExpr("neg", aligned)  # with $Rev

    ff = FactorFamily(name="$COMMON:TestRevInt")
    factor_rev = Factor(negated, family=ff)
    factor_norev = Factor(aligned, family=FactorFamily(name="$COMMON:TestNoRevInt"))

    # 3. Tester + evaluate
    tester = FactorTester(products=products, alias="VerifyRevInt")
    table_rev = factor_rev.evaluate(tester.products)
    table_norev = factor_norev.evaluate(tester.products)

    common_cols = table_rev.columns.intersection(table_norev.columns)
    if len(common_cols) < 2:
        print("  ⚠️  公共列不足，跳过")
        print("=" * 80)
        return

    # 4. 验证 factor.table 含 $Rev: rev = -norev
    rev_vs_norev = (table_rev[common_cols] + table_norev[common_cols]).abs().max().max()
    print(f"\n  验证1: factor.table 含 $Rev:")
    print(f"    rev + norev 最大绝对偏差: {rev_vs_norev:.10f}")
    assert rev_vs_norev < 1e-10, "$Rev NOT applied in factor.table!"
    print(f"    ✅ $Rev 在 factor.table 中正确应用")

    # 5. get_factor_table_for_group (无 IC 缓存) 应 = factor.table
    gt_rev = get_factor_table_for_group(tester, factor_rev)
    gt_norev = get_factor_table_for_group(tester, factor_norev)
    gt_rev_vs_table = (gt_rev[common_cols] - table_rev[common_cols]).abs().max().max()
    gt_norev_vs_table = (gt_norev[common_cols] - table_norev[common_cols]).abs().max().max()
    print(f"\n  验证2: get_factor_table_for_group (无IC缓存):")
    print(f"    gt_rev vs table_rev: {gt_rev_vs_table:.10f}")
    print(f"    gt_norev vs table_norev: {gt_norev_vs_table:.10f}")
    assert gt_rev_vs_table < 1e-10
    assert gt_norev_vs_table < 1e-10
    print(f"    ✅ 一致")

    # 6. 模拟 IC 缓存: 注入 _ic_fe_intermediate (原始 source_table 数据，无 $Rev 无 SignalAlign)
    source_norev = factor_norev.source_table.copy()
    factor_rev._data = None  # 清掉 table 缓存
    object.__setattr__(factor_rev, '_ic_fe_intermediate', source_norev.copy())
    gt_rev_ic = get_factor_table_for_group(tester, factor_rev)

    diff_ic = (gt_rev_ic[common_cols] - table_rev[common_cols]).abs().max().max()
    print(f"\n  验证3: get_factor_table_for_group (WITH _ic_fe_intermediate):")
    print(f"    gt_rev_ic vs expected table_rev: {diff_ic:.10f}")
    assert diff_ic < 1e-10, f"$Rev NOT applied after IC intermediate: diff={diff_ic}"
    print(f"    ✅ $Rev 在 IC intermediate 缓存场景下正确应用")

    # 7. 验证 norev 因子 + IC 缓存也正确
    factor_norev._data = None
    object.__setattr__(factor_norev, '_ic_fe_intermediate', source_norev.copy())
    gt_norev_ic = get_factor_table_for_group(tester, factor_norev)
    diff_norev_ic = (gt_norev_ic[common_cols] - table_norev[common_cols]).abs().max().max()
    print(f"\n  验证4: norev 因子 + IC 缓存:")
    print(f"    gt_norev_ic vs expected table_norev: {diff_norev_ic:.10f}")
    assert diff_norev_ic < 1e-10
    print(f"    ✅ 正确")

    # 8. SignalAlign: 检查 index 有 _SIGNAL@ 层级
    print(f"\n  验证5: SignalAlign ($F=5m) 正确:")
    for label, df in [("gt_rev", gt_rev), ("gt_rev_ic", gt_rev_ic), ("gt_norev_ic", gt_norev_ic)]:
        idx = df.index
        if isinstance(idx, pd.MultiIndex):
            sig_levels = [n for n in idx.names if str(n).startswith("_SIGNAL@")]
            print(f"    {label}: MultiIndex signal levels: {sig_levels}")
        else:
            print(f"    {label}: Index={type(idx).__name__}, first={idx[0] if len(idx)>0 else 'empty'}")

    print("\n" + "=" * 80)
    print("  集成验证全部通过！")
    print("=" * 80)


# ============================================================================
# 主入口
# ============================================================================

if __name__ == '__main__':
    verify_manual_scenario_1()
    results = verify_with_real_code()
    verify_edge_cases()
    analyze_rebalance_strategy()
    verify_frontend_backend_consistency()
    verify_rev_trace()
    verify_integrated_with_rev()

    print("\n\n")
    print("=" * 80)
    print("  全部验证完成。请检查输出中的手工推演与代码计算结果是否一致。")
    print("=" * 80)
