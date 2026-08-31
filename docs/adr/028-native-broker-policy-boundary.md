# ADR-028：Native Broker Policy 与 TargetStrategy 的边界

> **状态：已被 [ADR-032](032-strategy-book-and-counterparty-boundary.md) 取代。** 本文档的 `BrokerModule`/`NativeBroker`
> 已改名为 `StrategyBookModule`/`StrategyBookSimple`（只做策略登记+账本路由），
> "迁移计划"里阶段 4-9（`BrokerModule` 暴露 9 个 policy selector，各模块调用
> broker policy）的方向已被放弃——正文以下内容保留作历史决策记录，不再是当前架构。

- **日期**：2026-07-01
- **状态**：已接受（2026-07-01 审计后修订，见下）
- **决策者**：FactorTester 团队

---

## 审计更新（2026-07-01）

对照代码复核后订正了两处：

1. **背景遗漏了4个模块**：`PositionSizingModule`（数量取整）、`LiquidityModule`
   （流动性截断）、`SlippageModule`（滑点）、`FeeModule`（手续费）——这4个是
   ADR-027 在同一天已经点名的、同一条订单流水线里的真实模块，原背景只列了7个，
   漏了这4个。已补入下方背景清单。
2. **`min_lot_policy = none` 与实际代码矛盾**：`PositionSizingModule` 早已注册在
   默认模块表里，`quantity_rounding_policy` 默认值是 `floor_to_lot`——每次回测都
   会把订单数量向下取整到最小手数，这本身就是一个 min-lot policy，不是"没有"。
   已在 NativeBroker 一节改正。

另外发现 `OrderExecutionModule.matching_model` 声明了 `bar_volume_limited` 选项，
但全仓库没有任何代码分支真正处理它——是个挂在下拉菜单里但没接线的死选项，真正
做"按成交量限流"的是 `LiquidityModule.liquidity_mode`。迁移计划里加了一步专门
处理这个遗留问题，避免 `BrokerModule` 把死选项也继承过去。

具体执行步骤见配套文档
[ADR-128：Native Broker Policy 迁移实施计划](128-native-broker-policy-implementation-plan.md)。

## 背景

Native event-driven backtest 当前已经有订单生命周期，但语义分散在多个模块中：

- `TargetStrategyModule` 的子类生成目标权重，例如分组回测和 Long-Short；
- `OrderBookModule` 把目标权重和当前账本状态转换为订单意图；
- `PositionSizingModule` 把订单数量取整到最小手数（`floor_to_lot`/`nearest_lot`），
  作为 `OrderBookModule.size_order` 的 FlowOverride；
- `LiquidityModule` 按成交量参与率截断订单数量（`infinite`/`volume_participation`），
  同样是 `size_order` 的 FlowOverride；
- `GroupMembershipModule.schedule_order_execution` 当前还承担部分订单排程和撤单逻辑；
- `OrderExecutionModule` 决定成交价；
- `LedgerCashConstraintModule` 处理现金不足时的缩单；
- `SlippageModule` 在成交价基础上叠加滑点（`none`/`fixed_bps`）；
- `FeeModule` 计算手续费；
- `OrderLifecycleModule` 确认订单终态；
- `LedgerModule` 根据订单结果更新现金与持仓。

这些组合起来已经形成了一套内置 broker 行为，但代码上还没有把“订单如何被接受、
撤销、排程、成交、拒绝和确认”的语义集中表达。与此同时，`TargetStrategyModule`
容易被误解为 broker 的一部分，因为它输出最终会变成订单的 `target_weights`。

`SlippageModule`/`FeeModule` 严格说是成交价格确定之后的成本模型（前端 UI 上也
单独分在"费用"tab，不在"订单执行"tab），不是"这笔订单是否被接受/如何撮合"的
broker 语义，本 ADR 的 `BrokerModule` 范围不包含它们——见下方"边界"一节的
显式说明。

## 决策

新增 `BrokerModule` 作为订单行为 policy 服务，但它不接管 scheduler，也不包含
`TargetStrategyModule`。

核心链路保持：

```text
TargetStrategyModule -> OrderBookModule -> BrokerModule policies -> LedgerModule
```

### 目标策略模块（TargetStrategyModule）

`TargetStrategyModule` 负责“想要什么仓位”。它的子类只生成 target，不关心订单后续处理：

- `GroupMembershipModule`：根据因子信号、分组数、分组序号和分配方式生成目标权重；
- `LongShortCompositionModule`：根据若干源策略的 target 组合成新的 long-short target；
- 未来其他 target strategy 也只需要输出 `TargetStrategyModule.target_weights`。

`TargetStrategyModule` 不是 broker 的子模块，也不应知道订单是否被撤销、拒绝、
部分成交或以什么价格成交。

### 订单簿模块（OrderBookModule）

`OrderBookModule` 是 target 与 broker 之间的转换层：

- 输入：`target_weights`、当前权益、持仓、价格、合约乘数等；
- 输出：订单意图和数量 delta；
- 不负责 broker-side 订单有效期、撤单、撮合、成交确认。

### Broker 模块（BrokerModule）

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

### 原生 Broker（NativeBroker）

当前 native 默认行为应被命名并复刻为 `NativeBroker`，默认字段为：

- `broker_model = native_broker`
- `cancel_policy = replace_pending_same_product`
- `order_validity = next_signal`
- `matching_policy = next_bar_open_full_fill`（映射自 `OrderExecutionModule.
  matching_model = next_bar_full_fill`，是重命名不是照搬字符串；"成交多少"
  这部分实际由 `LiquidityModule.liquidity_mode = infinite` 决定，`matching_model`
  自己声明的 `bar_volume_limited` 选项当前未接线，见"审计更新"）
- `accept_policy = always_accept`（`Order.reject_reason`/`OrderStatus.REJECTED`
  管子已经存在于 `order.py`/`order_lifecycle.py`，只是当前没有任何模块真的赋值，
  BrokerModule 接入 reject 分支时可以直接复用，不用新建状态）
- `cash_policy = rescale_buy_orders`
- `min_lot_policy = floor_to_lot`（映射自 `PositionSizingModule.
  quantity_rounding_policy`，默认 `floor_to_lot`，另有 `nearest_lot` 可选；
  **不是 `none`**——这是本 ADR 审计后订正的一处）
- `fill_cap_policy = no_cap`（映射自 `LiquidityModule.liquidity_mode = infinite`，
  另有 `volume_participation` 可选；ADR 首版遗漏了这个 policy 维度，一并补上）
- `price_band_policy = ignore`
- `order_state_model = simple_filled_rejected_cancelled`（指**终态**语义简单，
  只有 filled/rejected/cancelled 三种归宿；实际 `OrderStatus` 枚举还有
  draft/scheduled/accepted 三个中间态，总共6个值，不是只有3个状态）

这些字段是 policy selector，不是 policy 本身。`NativeBroker` 根据 selector 组装
callable policy。

`SlippageModule`（`slippage_mode`）与 `FeeModule` 不对应任何 broker policy
selector——它们是成交价确定之后的成本模型，明确排除在 `BrokerModule` 范围外
（见"背景"一节末尾的边界说明）。

### 自定义 Broker（CustomBroker）

CLI / factor workspace 可以注册自定义 broker 或单个 policy，并通过 id 传入
`BrokerModule`。前端不直接传任意 callable。

Custom broker 可以覆写完整 broker，也可以只覆写部分 policy。未覆写的方法使用
`NativeBroker` 默认 policy。

### OrderStore 与 BrokerStore

`OrderStore` 不整体迁移到 broker。它继续表达订单对象、订单意图、订单事件和 trace
等通用事实。

`BrokerStore` 只保存 broker runtime 自身状态，例如：

- `broker_by_strategy`
- `ledger_ids_by_strategy`
- broker policy cache
- broker session state

`ledger_id` 是账本标识，不是 broker 自己的持仓容器。`BrokerModule` 负责把
strategy/order 路由到 `ledger_id`；现金、`ProductPosition` 和 `lots` deque 仍由
`Ledger` 保存，并由 `BacktestRunState.ledgers[ledger_id]` 索引。`NativeBroker`
为每个 strategy 分配私有 `ledger_id`，`CustomBroker` 可以让多个 strategy 共享同一
`ledger_id`，也可以在订单级覆盖 `ledger_id` 来支持同一 strategy 操纵多个账本。

现阶段 `OrderStore.pending_orders` 先保留在 `OrderStore`。如果后续确认它只表示
broker-side open orders，再迁移或重命名为 `BrokerStore.open_orders`。

## 迁移计划

0. 先处理 `OrderExecutionModule.matching_model` 的 `bar_volume_limited` 死选项：
   要么删掉这个选项，要么把它接到 `LiquidityModule` 的截断逻辑上——两者选一，
   不能让 `BrokerModule` 在不知情的情况下把这个死选项继承过去。
1. 新增 `BrokerModule`、`NativeBroker`、`BrokerStore`、`BrokerRegistry` 和 policy
   callable protocol。
2. 注册 broker 字段，默认值复刻当前 native 行为——包括 `min_lot_policy=
   floor_to_lot`（不是 `none`）和新增的 `fill_cap_policy=no_cap`。
3. 在 PRE_REPLAY 中增加 `resolve_broker` flow，按 strategy 构造 broker object。
4. `GroupMembershipModule.schedule_order_execution` 改为调用 broker 的排程和撤单
   policy，但仍从 `OrderStore.pending_orders` 读取旧 pending order。
5. `OrderExecutionModule` 改为调用 broker 的成交价 policy。
6. `PositionSizingModule` 改为调用 broker 的 min-lot policy。
7. `LiquidityModule` 改为调用 broker 的 fill-cap policy。
8. `LedgerCashConstraintModule` 改为调用 broker 的现金 policy。
9. `OrderLifecycleModule` 改为调用 broker 的终态 policy。
10. 每一步都用控制变量测试证明默认 `NativeBroker` 行为与迁移前一致——不只测
    默认值，也要覆盖每个 policy 现有的非默认可选项（`nearest_lot`、
    `volume_participation` 等），因为这些是已经上线的真实用户选项，不是假设。

具体到每一步该跑哪些回归测试、以什么顺序推进，见配套的实施计划文档
[ADR-128：Native Broker Policy 迁移实施计划](128-native-broker-policy-implementation-plan.md)。

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
