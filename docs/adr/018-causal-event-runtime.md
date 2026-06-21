# ADR-018：因果事件运行时与回测模块边界

- **日期**：2026-06-20
- **状态**：已采纳
- **取代**：ADR-009 中的固定阶段 DES 与 `EventDrivenFactor`

## 背景

旧原型为每个时间点预先放入 MARKET_DATA、FACTOR、SIGNAL、ORDER、FEE、
MARGIN、LIQUIDITY、FILL、PNL、REPORT 十类事件。它仍然是固定时间循环，
只是把循环阶段包装成事件，存在三个问题：

1. 没有事件之间的因果关系，订单并不是由信号产生，成交也不是由订单产生。
2. 队列规模为 `O(时间点 × 阶段数)`，无法自然表达延迟成交、撤单和异步行情。
3. 因子被分裂为 FactorExpr 与 EventDrivenFactor 两套作者接口。

离散事件仿真的事件应经历未触发、已调度、已处理的单向生命周期；待处理事件
进入按 `(timestamp, priority, sequence)` 排序的 Future Event List。事件处理器
可以因果地产生后续事件。

## 决策

### 每次回测独占一个 EventRuntime

“事件池”统一命名为 `EventRuntime`，避免与对象复用池混淆。它由以下部分组成：

- **Future Event Queue**：尚未处理的事件堆。
- **Event Bus**：`EventTopic → handlers` 的订阅表。
- **Event Sources**：行情回放、实盘行情、定时器、交易所和结算源。
- **Event Journal**：已处理事件及订阅者数量，用于回放和诊断。

`EventRuntime` 必须是 run-scoped，不能由用户、页面或进程全局共享。`run_id`
贯穿所有事件；多用户同时运行时拥有不同 runtime、queue、journal 和 actor 状态。

### BacktestRunner 是唯一装配入口

`BacktestRunner` 是每次运行的 Composition Root，负责验证并连接：

- 一份共享的行情源、`MarketState`、截面屏障和 Factor actors；
- 多个 `StrategyLane`，每个 lane 独占 strategy identity、portfolio、Ledger 和
  OrderManager；
- 一个或多个 `ExecutionVenue`。共享 Venue 表示共同消费执行容量，隔离 Venue
  表示候选策略各自在独立虚拟市场中评估。

Runner 不实现策略、费用、风控或成交算法。它只固定 actor 生命周期、订阅关系和
标准结果收集。每个截面关闭后发布低优先级 `REPORT`，确保同时间戳的信号、风控、
订单和成交完成后再记录各 portfolio 快照。

所有订单 ID 包含 run 与 portfolio 命名空间；Fill ID 继承 order identity，保证同一
run 中多策略和多 Venue 不会碰撞。

### 事件必须因果地产生

```text
ProductPrice
  → MarketSliceClosed
  → FactorSignal
  → PortfolioIntent
  → OrderSubmitted
  → OrderAccepted / OrderRejected
  → Fill
  → Settlement / MarginCall / Report
```

行情回放源只把下一条行情放入队列，处理完成后再放下一条，不能一次装载全部
时间点。处理器不得向过去发布事件。同一时间戳按 priority、sequence 确定性
执行，并设置单时间戳事件数量上限以发现因果环。

当多个产品分别发送价格时，`MarketSliceBarrier` 在预期产品全部到达后发布
`MarketSliceClosed`。横截面因子订阅该屏障事件；不需要完整截面的时序算子可
直接订阅产品价格事件。

### 一个 Factor DSL，多个执行器

因子作者只编写 FactorExpr。执行计划决定使用：

- **Batch executor**：现有向量化 `evaluate()`，结果由
  `PrecomputedFactorPublisher` 在行情截面关闭时发布 `FactorSignal`。
- **Incremental executor**：FactorExpr 编译出的有状态执行对象，在行情事件上
  更新窗口和状态并发布同一种 `FactorSignal`。

`IncrementalFactorExecutor` 是编译目标，不是第二套作者 API。旧
`EventDrivenFactor` 不再作为公共概念。

### 状态修改权属于明确 actor

| Actor | 订阅 | 可修改的状态 | 产生 |
|---|---|---|---|
| MarketState | ProductPrice | 最新可见行情 | 无 |
| FactorExecutor | 行情/截面关闭 | 因子窗口和内部状态 | FactorSignal |
| Strategy | FactorSignal/Timer | 策略内部状态 | PortfolioIntent |
| OrderManager | PortfolioIntent | 订单生命周期 | OrderSubmitted |
| Broker/Execution | OrderSubmitted/行情 | 模拟交易所状态 | Accepted/Rejected/Fill |
| Ledger | Fill/Settlement | 持仓、现金、费用、盈亏 | Snapshot/RiskEvent |
| RiskManager | Intent/Order/Fill | 风险限额状态 | Reject/MarginCall |

信号和组合模块不得直接修改持仓；只有 Ledger 可以根据 Fill、Settlement 等会计
事件修改账户状态。

### 回测叠加模块

叠加模块按事件边界组合，而不是塞进一个 `group_configs` 字典：

| 层 | 模块 | 主要职责 |
|---|---|---|
| 输入 | Calendar / Instrument / ContractSpec | 时钟、交易时段、乘数、最小价位、币种 |
| 行情 | DataFeed / Roll / Adjustment | 行情事件、连续合约换月、复权语义 |
| 因子 | FactorPlan / Batch / Incremental | 因子图编译、预热、信号发布 |
| 组合 | Ranking / Grouping / Allocator | 排序、分组、目标权重或目标数量 |
| 调仓 | Schedule / RebalancePolicy | 定时、持有、recycle、换仓条件 |
| 风险 | Constraints / Margin / Collateral | 下单前限制、保证金、追加保证金 |
| 订单 | OMS / Sizer / TickLotRules | 差额订单、生命周期、价位和手数规整 |
| 执行 | Broker / Fill / Slippage / Liquidity | 接受拒绝、部分成交、延迟、容量和滑点 |
| 费用 | Commission / Tax / FX | 开平今费用、税费、币种转换 |
| 会计 | Ledger / Settlement / PnL | 现金、持仓、盯市、结算、已实现与未实现盈亏 |
| 输出 | Analyzer / Result / Journal | 指标、标准结果、事件回放 |
| 控制 | Progress / Cancellation / Telemetry | 进度、取消、结构化观测，不修改交易状态 |

模块可以合并实现，但不能跨越状态所有权。例如 FeeModel 可以由 Broker 调用，
最终费用仍随 Fill 进入 Ledger；流动性模型可以产生部分成交，不能直接裁剪持仓。

### 纯向量执行是受限执行器

无费用、无流动性、无保证金、无路径依赖持仓且成交语义等价时，可以使用纯
向量执行器。它不是另一套策略模型，必须消费相同因子与组合意图，并返回相同
标准结果。执行计划一旦要求订单生命周期、结算或路径依赖状态，就必须使用
事件运行时。

## 后果

- 延迟成交、部分成交、定时器、换月、结算和追加保证金可以自然进入队列。
- 行情、因子、策略和会计可独立测试，也能替换为外部框架 adapter。
- 事件数量取决于真实发生的行为，而不是时间点乘固定阶段数。
- 需要逐步把现有 `simulate_group_trading_book` 拆成 actor；迁移期间以结果对照
  测试锁定期货费用、保证金和结算语义，不能一次性重写后宣称等价。
- 原固定阶段 `EventDrivenEngine/WorldState/BacktestContext` 原型及其 models、
  orders、factors 已删除；原生实现统一位于 `tools/backtest/event_driven/`，外部
  框架边界统一位于 `tools/backtest/adapters/`，不提供旧 import 路径 fallback。
