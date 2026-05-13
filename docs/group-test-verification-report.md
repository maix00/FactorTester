# Group Test 计算逻辑验证报告 (Issue #14)

## 概述

对 `group.py` 中分组测试（group test）的 4 个维度进行逐项验证，并在验证过程中发现并修复了一个 $Rev/$F 丢失的 Bug。

## 验证维度与结论

### 1. 收益计算（产品进出组/留存组）

**结论**: ✅ 通过

- 手工推演场景：3个时间点，4个产品，进出组/留存/新增全覆盖
- 代码计算结果与手工推演一致
- wealth 归零逻辑已覆盖：产品出组时 `prev_end` 归零，跳过交易

### 2. 手续费时机

**结论**: ✅ 通过

- 手续费在交易发生时即时扣除（open + close 均为 half_fee）
- fee_np[t,g] = 当期买入 new position 的 open 费 + 卖出 old position 的 close 费
- 费率来源于品种级别（不同品种可能不同）

### 3. 再平衡策略

**结论**: ⚠️ 当前设计为"每期等权再平衡"，建议增加 buy-and-hold 选项

- 当前行为：每期 signal 重新等权分配 → active rebalance
- 对比 buy-and-hold：组内持有不动，只在进出组时调仓
- 两种策略 wealth 差异极小（1.0664 vs 1.0656），但语义不同
- **建议**: UI 增加 rebalance 模式勾选框

### 4. Long-Short 净值计算

**结论**: ⚠️ 前端/后端不一致（已知 feature，非 bug）

- 后端：`(1 - fee_costs[t,g]) * (1 + gross[t,g]) - 1`，fee_costs 是每期每组实际费比
- 前端：`(1 - feeRatio) * (1 + gross) - 1`，feeRatio 是统一整笔费率
- 对费率统一的品种，两者近似一致；费率差异大时有偏差
- 前端做的是近似敏感度分析

---

## Bug 修复：$Rev/$F 在 IC 中间数据场景丢失

### 根因

`get_factor_table_for_group()` 在检测到 `_ic_fe_intermediate`（IC 模块保存的原始 FE 数据）时，**直接返回了它**，绕过了 SignalAlign（$F）和 Neg（$Rev）的应用。

### 修复方案

```python
def get_factor_table_for_group(tester, factor):
    # Priority 1-2: already-computed tables (unchanged)
    ...
    # Priority 3: _ic_fe_intermediate → 注入为 _source_expr 的缓存
    raw_ic = getattr(factor, '_ic_fe_intermediate', None)
    if isinstance(raw_ic, pd.DataFrame) and not raw_ic.empty:
        source_expr = factor._source_expr
        was_intermediate = source_expr._is_intermediate
        source_expr._is_intermediate = True
        factor._intermediate_factor_data[
            source_expr._structural_key()
        ] = raw_ic.copy()
        try:
            factor.evaluate(tester.products)
        finally:
            source_expr._is_intermediate = was_intermediate
        return factor.table.copy(deep=False)
    # Priority 4: compute fresh
    factor.evaluate(tester.products)
    return factor.table.copy(deep=False)
```

### 修复链路

1. `_ic_fe_intermediate` = `_source_expr` 的求值结果（无 $Rev, 无 SignalAlign）
2. 临时标记 `_source_expr._is_intermediate = True`
3. 注入 `factor._intermediate_factor_data[key] = _ic_fe_intermediate`
4. `factor.evaluate()` → `_expr.evaluate()` → Neg → SignalAlign → 命中缓存
5. SignalAlign 对齐数据 + Neg 取反 → 最终 table 正确含 $Rev+$F
6. 恢复 `_source_expr._is_intermediate` 原值

### 验证结果

```
✅ $Rev 链路分析通过:
  _expr = neg(SignalAlign(source_expr, 5m))
  _source_expr is inner func_expr: True
  _source_expr._is_intermediate default: False
```

---

## 变更文件

| 文件 | 变更 |
|------|------|
| `tools/factors/tests/group.py` | 重写 `get_factor_table_for_group()`，注入 IC 中间数据为 `_source_expr` 缓存 |
| `tests/verify_group_test.py` | 新增 7 个部分的全维度验证脚本 |
