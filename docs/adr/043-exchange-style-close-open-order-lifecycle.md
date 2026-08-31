# ADR-043：交易所式订单生命周期与按 K 线容量撮合

- **日期**：2026-07-23
- **状态**：已接受
- **GitHub Issue**：#144
- **相关决策**：ADR-018、ADR-020、ADR-027、ADR-031、ADR-034、ADR-041、ADR-042

## 背景

原生引擎目前把一个目标差额变成一个带符号的 `Order`，再按信号 K 线成交量裁剪，随后在下一根 K 线开盘把剩余数量作为完整成交结算。这会丢失未成交意图，也混淆订单请求、执行容量、成交和账本结算。

国内期货反转需要区分平今、平昨和开仓指令，它们可能在不同时间成交；未成交的平仓不能提前释放保证金。

FIX、vn.py、LEAN 和 Backtrader 的共同模型是：一个原子订单有稳定身份，可以收到多个不可变成交，并投影累计成交量和剩余数量。部分成交不会创建子订单。

## 决策

### 领域模型

`Order` 继续表示原子可执行指令，不新增竞争性的 `OrderLeg` 实体。协调过渡使用：

```text
Parent Intent
└── OrderGroup（只负责编排和审计）
    ├── Order(offset=close_today) ── Fill 0..N
    ├── Order(offset=close_yesterday) ── Fill 0..N
    └── Order(offset=open, waiting on closes) ── Fill 0..N
```

`OrderGroup` 永远不排队、不撮合、不成交、不结算；它的状态和数量从子订单与成交派生。

每个 Order 带稳定的 `order_id`、`order_group_id`、`parent_intent_id`、`leg_role`、`offset`、方向、请求数量、最近接受的 revision、有效期和可执行时间。提交、取消、替换动作保留不可变请求身份及 revision 链。取消请求不等于取消确认；取消或替换等待期间仍可能到达成交。

每次执行创建一个不可变 `Fill`。Order 投影为：

```text
cumulative_filled = sum(Fill.quantity)
active_leaves = current_order_quantity - cumulative_filled
terminal_unfilled = current_order_quantity - cumulative_filled
```

进入终态后 active leaves 为零，但 terminal unfilled 仍可审计。费用、盈亏、现金和保证金影响属于与 Fill 关联的结算记录。

### 调度与撮合

保留 `EventKind.ORDER`。每个可操作 Order 带不可变 attempt payload；attempt 不是子订单。部分成交会在下一根可用行情 K 线为同一 Order 安排新的 attempt；旧 attempt 按 revision 身份跳过。

一个时间戳内，执行场所处理完整批次：

```text
收集可操作 Order
→ 合并显式的账户级冲突
→ 分配并结算所有降低风险的成交
→ 重新计算持仓、现金、保证金和购买力
→ 激活已满足依赖
→ 分配并结算所有增加风险的成交
```

降低风险优先不等于先卖后买；同一时间使用提交时间和 Order ID 排序，不能依赖字典顺序。流动性限制适用于所有订单，包括平仓；平仓优先但不虚构容量。购买力和硬保证金利用率只约束增加保证金的成交。

默认反转策略只有在所需平仓全部结算后才激活开仓。部分释放需要命名的交错策略和对冲记账。

### K 线成交量因果性

撮合精度必须显式声明：

| 模式 | 容量已知时间 | 因果执行时间 |
|---|---|---|
| `next_bar_full_fill` | 不限制容量 | 下一根 K 线开盘 |
| `lagged_bar_volume` | 上一根已完成 K 线 | 当前 K 线开盘 |
| `execution_bar_volume` | 执行 K 线完成 | 执行 K 线结束 |
| `tick_orderbook` | 观测到成交/深度 | 事件时间 |

引擎不得把下一根开盘成交和同一根 K 线的最终成交量结合。精确模式在需要交易所时间戳或逐笔/盘口数据而数据不可用时必须拒绝 K 线代理。

### 目标对账

对于目标意图，令 `A` 为实际持仓，`R` 为保留的有符号剩余，`T` 为最新目标。若 `A + R == T`，保留订单；否则替换未成交剩余，保留既有成交，并把从 `A` 到 `T` 的订单组标记为被取代。

差额意图仍是加法语义，除非策略显式选择 replace、merge、coexist 或 defer。不能用特殊 `$F=1m` 分支改变这些语义。

## 可观测性与 CLI

紧凑 step 输出显示组、Order、状态、请求量、累计成交、活跃剩余、终态未成交、已用容量和下一次 attempt。完整详情展开 attempt、动作 revision、Fill 和关联结算，不能截断。所有 CLI 检查命令同时提供机器可读 JSON，并使用真实 FactorTester 后端。

## 验收

- 多头 `10` 变空头 `5` 时生成总量为 `10` 的平仓订单和数量为 `5` 的开仓订单，不能由一个原子 Order 混合平仓与开仓。
- 平仓成交 `6/10` 只释放已结算的保证金，剩余部分继续存活，顺序开仓继续等待。
- 平仓受成交量限制，但不受保证金硬上限缩小。
- 一个 Order 可以在多根可用 K 线成交，并保持一个 Order ID。
- 容量按场所、合约、执行 K 线和方向只消耗一次。
- 降低风险的成交在增加风险的成交计算购买力前结算。
- 队列内容等于非终态订单索引中的可操作子集。
- 已取消或被取代的 attempt 不能执行。
- 快速更新目标不会把旧剩余量重复加进新目标差额。
- 原子路径与分腿路径只有在同价完整成交、相同手数/取整、无每单最低费用且无中间约束时才一致。
- 精确执行在 offset、手数年龄、费用/保证金规则、交易所时间戳或必需逐笔/深度数据缺失时，在状态变更前失败。

## 参考

- FIX Trading Community：订单状态变化与交易业务领域；
- vn.py：`OrderData` 与 `TradeData`；
- QuantConnect LEAN：`OrderTicket`、`OrderEvent` 与目标订单；
- Backtrader：订单生命周期和成交量填充器。
