"""DEBUG-snapshot: 最小化后端逻辑检查。"""
import sys, os
sys.path.insert(0, '/Users/maxdeux/Documents/GTHT/Codes')

import numpy as np
import pandas as pd
import json

# --- 测试 1: GroupRunResult slots ---
print("=== Test 1: GroupRunResult hold_amounts_np ===")
from tools.factors.tests.single_factor_test.group.result import GroupRunResult
r = GroupRunResult(
    fee_costs_np=np.zeros((5,2)),
    trade_notional_ratio_np=np.zeros((5,2)),
    gross_returns_np=np.zeros((5,2)),
    product_gross_contrib_np=np.zeros((5,2,3)),
    product_fee_contrib_np=np.zeros((5,2,3)),
    returns_np=np.zeros((5,3)),
    period_returns_np=np.zeros((5,3)),
    membership_np=np.zeros((5,2,3)),
    products_by_group={0: {pd.Timestamp('2025-01-01'): ['A', 'B']}},
    valid_cols=['A', 'B', 'C'],
    open_fee_vec=np.zeros(3),
    close_fee_vec=np.zeros(3),
    close_today_fee_vec=np.zeros(3),
    close_yesterday_fee_vec=np.zeros(3),
    index_list=[pd.Timestamp('2025-01-01')],
    multi_session_active=False,
    rebalance_mode='equal_weight',
    report_df=pd.DataFrame(),
)
print(f"  hold_amounts_np = {r.hold_amounts_np}")
print(f"  hasattr: {hasattr(r, 'hold_amounts_np')}")

# --- 测试 2: index_list.index 兼容性 ---
print("\n=== Test 2: index_list.index 兼容性 ===")
ts1 = pd.Timestamp('2025-01-01')
ts2 = pd.Timestamp('2025-01-02')
idx_list1 = [ts1, ts2]
try:
    i = idx_list1.index(ts1)
    print(f"  ✅ Timestamp .index(): {i}")
except Exception as e:
    print(f"  ❌ Timestamp .index() FAILED: {e}")

# tuple with numpy types
t1 = (pd.Timestamp('2025-01-01'), np.int64(0))
t2 = (pd.Timestamp('2025-01-02'), np.int64(0))
idx_list2 = [t1, t2]
try:
    i = idx_list2.index(t1)
    print(f"  ✅ Tuple(Timestamp, int64) .index(): {i}")
except Exception as e:
    print(f"  ❌ Tuple .index() FAILED: {e}")

# --- 测试 3: 模拟 get_group_snapshot 金额注入 ---
print("\n=== Test 3: get_group_snapshot 金额注入逻辑 ===")
best_idx_entry = pd.Timestamp('2025-01-01')
t_idx = 0
hold_np = np.array([[[100.0, 50.0, 0.0], [200.0, 0.0, 100.0]]])  # (1, 2, 3)
valid_cols = ['A', 'B', 'C']
col_to_pos = {col: i for i, col in enumerate(valid_cols)}

for g in range(2):
    current_display = [
        {'name': 'A', 'desc': 'DescA'},
        {'name': 'B', 'desc': 'DescB'},
        {'name': 'C', 'desc': 'DescC'},
    ]
    g_amounts = hold_np[t_idx, g, :]
    total_amount = float(np.sum(g_amounts))
    
    for d in current_display:
        pname = d['name']
        pos = col_to_pos.get(pname)
        if pos is not None and pos < len(g_amounts):
            amt = float(g_amounts[pos])
            d['amount'] = round(amt, 6)
            d['weight'] = round(amt / total_amount, 6) if total_amount > 0 else 0.0
            d['pending_exit'] = amt < total_amount * 0.0001
    
    print(f"  Group {g}: total={total_amount}")
    for d in current_display:
        print(f"    {d['name']}: amount={d.get('amount')}, weight={d.get('weight')}, pending_exit={d.get('pending_exit')}")

# --- 测试 4: JSON 序列化 ---
print("\n=== Test 4: JSON 序列化 ===")
test_dict = {'amount': np.float64(0.0), 'weight': np.float64(1.0/3.0), 'pending_exit': True}
try:
    j = json.dumps(test_dict, default=str)
    print(f"  ✅ NumPy in JSON: {j}")
except Exception as e:
    print(f"  ❌ JSON FAILED: {e}")

# round(numpy) 返回类型
x = round(np.float64(1.23456789), 6)
print(f"  round(np.float64, 6) = {x} ({type(x).__name__})")

print("\n=== ALL DONE ===")
