# ADR-028：Native Broker Policy 与 TargetStrategy 的边界

- **日期**：2026-07-01
- **状态**：已接受
- **决策者**：FactorTester 团队

---

## 背景

Native event-driven backtest 当前已经有订单生命周期，但语义分散在多个模块中：

- `TargetStrategyModule` 的子类生成目标权重，例如分组回测和 Long-Short；
- `OrderBookModule` 把目标权重和当前账本状态转换为订单意图；
- `GroupMembershipModule.schedule_order_execution` 当前还承担部分订单排程和撤单逻辑；
- `OrderExecutionModule` 决定成交价；
- `LedgerCashConstraintModule` 处理现金不足时的缩单；
- `OrderLifecycleModule` 确认订单终态；
- `LedgerModule` 根据订单结果更新现金与持仓。

这些组合起来已经形成了一套内置 broker 行为，但代码上还没有把“订单如何被接受、
撤销、排程、成交、拒绝和确认”的语义集中表达。与此同时，`TargetStrategyModule`
容易被误解为 broker 的一部分，因为它输出最终会变成订单的 `target_weights`。

## 决策

新增 `BrokerModule` 作为订单行为 policy 服务，但它不接管 scheduler，也不包含
`TargetStrategyModule`。

核心链路保持：

```text
TargetStrategyModule -> OrderBookModule -> BrokerModule policies -> LedgerModule
```

### TargetStrategyModule

`TargetStrategyModule` 负责“想要什么仓位”。它的子类只生成 target，不关心订单后续处理：

- `GroupMembershipModule`：根据因子信号、分组数、分组序号和分配方式生成目标权重；
- `LongShortCompositionModule`：根据若干源策略的 target 组合成新的 long-short target；
- 未来其他 target strategy 也只需要输出 `TargetStrategyModule.target_weights`。

`TargetStrategyModule` 不是 broker 的子模块，也不应知道订单是否被撤销、拒绝、
部分成交或以什么价格成交。

### OrderBookModule

`OrderBookModule` 是 target 与 broker 之间的转换层：

- 输入：`target_weights`、当前权益、持仓、价格、合约乘数等；
- 输出：订单意图和数量 delta；
- 不负责 broker-side 订单有效期、撤单、撮合、成交确认。

### BrokerModule

`BrokerModule` 负责注册 broker 字段、构造 broker object，并暴露 callable policy。
它是订单行为语义服务，不是 flow 编排器。现有订单相关 flow 仍由 scheduler 调用，
但在需要判断订单行为时调用 broker：

- 是否接受订单；
- 是否撤销旧 pending order；
- 订单何时生效；
- 使用什么成交价格；
- 现金不足时缩单还是拒单；
- 最小手数、涨跌停、交易时段等规则如何处理；
- 订单终态如何确认。

`BrokerModule` 不主动调用 `OrderBookModule`、`OrderExecutionModule`、
`LedgerCashConstraintModule`、`OrderLifecycleModule` 或 `LedgerModule`。
这些模块在自己的 flow 中调用 `broker_for(run_state, strategy)` 获得 broker，
再调用对应 policy。

### NativeBroker

当前 native 默认行为应被命名并复刻为 `NativeBroker`，默认字段为：

- `broker_model = native_default`
- `cancel_policy = replace_pending_same_product`
- `order_validity = next_signal`
- `matching_policy = next_bar_open_full_fill`
- `accept_policy = always_accept`
- `cash_policy = rescale_buy_orders`
- `min_lot_policy = none`
- `price_band_policy = ignore`
- `order_state_model = simple_filled_rejected_cancelled`

这些字段是 policy selector，不是 policy 本身。`NativeBroker` 根据 selector 组装
callable policy。

### CustomBroker

CLI / factor workspace 可以注册自定义 broker 或单个 policy，并通过 id 传入
`BrokerModule`。前端不直接传任意 callable。

Custom broker 可以覆写完整 broker，也可以只覆写部分 policy。未覆写的方法使用
`NativeBroker` 默认 policy。

### OrderStore 与 BrokerStore

`OrderStore` 不整体迁移到 broker。它继续表达订单对象、订单意图、订单事件和 trace
等通用事实。

`BrokerStore` 只保存 broker runtime 自身状态，例如：

- `broker_by_strategy`
- broker policy cache
- broker session state

现阶段 `OrderStore.pending_orders` 先保留在 `OrderStore`。如果后续确认它只表示
broker-side open orders，再迁移或重命名为 `BrokerStore.open_orders`。

## 迁移计划

1. 新增 `BrokerModule`、`NativeBroker`、`BrokerStore`、`BrokerRegistry` 和 policy
   callable protocol。
2. 注册 broker 字段，但默认值复刻当前 native 行为。
3. 在 PRE_REPLAY 中增加 `resolve_broker` flow，按 strategy 构造 broker object。
4. `GroupMembershipModule.schedule_order_execution` 改为调用 broker 的排程和撤单
   policy，但仍从 `OrderStore.pending_orders` 读取旧 pending order。
5. `OrderExecutionModule` 改为调用 broker 的成交价 policy。
6. `LedgerCashConstraintModule` 改为调用 broker 的现金 policy。
7. `OrderLifecycleModule` 改为调用 broker 的终态 policy。
8. 每一步都用控制变量测试证明默认 `NativeBroker` 行为与迁移前一致。

## 后果

### 正面影响

- Target strategy、order intent、broker policy、ledger 更新的语义分层更清楚；
- 默认 native broker 可以作为可复现基准；
- 高级用户可以通过 CLI / factor workspace 注册自定义 broker 或局部 policy；
- flow scheduler 仍保持业务无关，不被 broker 接管；
- Long-Short、分组回测和未来策略共享同一 broker 行为入口。

### 权衡

- 第一阶段会增加一层 broker indirection，但默认行为必须保持不变；
- 不能一次性把 `OrderStore.pending_orders` 迁走，否则会混淆 drafted order、
  order event 和 broker-side open order 的语义；
- policy selector 与 callable policy 需要严格测试，否则容易出现“字段显示变了但
  真实行为没变”或相反的问题。

## 参考

- Backtrader broker/order execution 模型
- Zipline blotter / slippage / commission 模型
- vn.py CTA/portfolio order management 语义
- QuantStart event-driven backtesting execution handler
