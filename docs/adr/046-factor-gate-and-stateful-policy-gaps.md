# ADR-046: 因子门控与有状态策略能力缺口

- **日期**：2026-07-28
- **状态**：待实现
- **关联**：ADR-019、ADR-020、ADR-041、ADR-042、ADR-045

## 背景

141 已新增 `cs_rank(mask=...)` 与 `cs_ordinal_rank(mask=..., ascending=...)`。
它们配合 `where` 能表达逐品种、逐时点、无状态的 eligibility、方向、阈值和
截面选择；固定 top-k / bottom-k 也可先形成整数名次再产生布尔门控。

但这些表达式只读取当前可得的因子值与 mask。它们不能读取实际持仓、现金池、
保证金、订单队列或成交生命周期。若将这些问题继续塞入 FactorExpr，会混淆
基础因子的经济含义、策略 intent、账户风险和实际执行，并破坏 replay/step 的
因果审计。

## 决策

因子表达式层保持无状态。它负责产生可审计的 factor value、eligibility、
long/short gate 与截面名次；Group Policy 消费这些输出形成成员资格和目标权重。

下列能力明确不由 FactorExpr 实现，作为待解决的策略/运行时能力登记：

| 能力缺口 | 正式归属 | 待验收语义 |
| --- | --- | --- |
| 候选不足、双侧重叠、最小成员数与不补 neutral | Group Policy | 每侧只从各自 eligible 候选选择；不足时少选或不交易；冲突有 reason code。 |
| 进入/退出滞回 | Position State Policy | 以已执行持仓为状态；entry/exit 阈值可不同且每一步可审计。 |
| no-trade 区与换手预算 | Rebalance Policy | 以当前权重和目标权重的偏离决定是否调仓；不改写 factor ranking。 |
| 止损、止盈、持有期退出 | Risk / Position Policy | 依赖入场价、最高/最低价、持仓时长和实际仓位。 |
| 共享现金池、总保证金与资金竞争 | Margin Budget / Buying Power | 以完整目标/订单 batch、账户权益和已占用保证金作出可复现 decision。 |
| 流动性参与率、部分成交和剩余续挂 | Execution / OrderScheduling | 以可成交 bar、订单状态和队列产生 fill/remaining lifecycle。 |
| 多策略冲突与净额化 | StrategyBook / Portfolio Policy | 在冻结 target intent 后处理，不回写因子值。 |
| 会话下单与价格时点 | Session / Execution Policy | 日历可作为 factor gate 输入；订单事件时间和成交价格仍由 execution 决定。 |

## 分组研究的当前可用边界

在上述能力落地前，分组回测可合法使用：

```python
eligible = liquidity_gate & data_available
rank = base_factor.cs_ordinal_rank(mask=eligible, ascending=False)
long_gate = rank <= k_long
```

或按比例：

```python
rank = base_factor.cs_rank(mask=eligible)
long_gate = rank >= threshold
```

这两种写法只定义“当前信号时刻谁进入候选集合”；它们不能宣称已经实现了
滞回、no-trade、风险控制或执行约束。

## 后续工作

1. 为 Group Policy 增加显式的双侧候选、冲突、候选不足和最小成员数诊断。
2. 按 ADR-041 的 `entry` / `exit` role 实现可回放的 position-state transition。
3. 将 no-trade/turnover budget 接入 rebalance decision，并在 step 中输出目标偏离与决策原因。
4. 按 ADR-042、ADR-020 完成 buying-power batch、流动性和部分成交 lifecycle 的验收。
5. 为策略层门控与基础 factor 单调性建立分开的报告与 attribution contract。
