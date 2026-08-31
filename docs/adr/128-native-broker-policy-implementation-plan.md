# ADR-128：Native Broker Policy 迁移实施计划

> **编号迁移说明：** 本文原文件名为 `028-native-broker-policy-implementation-plan.md`。因 ADR-028 已用于
> Native Broker Policy 与 TargetStrategy 的边界，本文迁移为 ADR-128；计划内容不因重编号改变。
>
> **状态：已被 [ADR-032](032-strategy-book-and-counterparty-boundary.md) 取代。** 只有“阶段 1：
> BrokerModule 骨架"（改名为 StrategyBookModule/StrategyBookSimple）落地了；阶段 2 起把各模块
> 改成调用 broker policy 的方向已放弃，不再执行。

- **对应决策**：[028-native-broker-policy-boundary.md](028-native-broker-policy-boundary.md)
- **日期**：2026-07-01
- **最终状态**：已取代；阶段 1 的骨架曾落地，阶段 2 以后未执行

---

## 目标

把分散在 `GroupMembershipModule.schedule_order_execution`、`OrderExecutionModule`、
`PositionSizingModule`、`LiquidityModule`、`LedgerCashConstraintModule`、
`OrderLifecycleModule` 六个模块里的订单行为语义（撤单/排程、成交价、最小手数、
流动性截断、现金约束、终态确认）收拢到 `BrokerModule` 暴露的 policy selector 后面，
且**每一步落地后，默认 `NativeBroker` 行为必须和迁移前逐笔一致**——这是本计划最
硬的约束，每个阶段都要用回归测试验证，不是到最后才测。

不做的事（复述 ADR 的边界，避免范围蔓延）：
- 不把 `TargetStrategyModule` 并入 broker；
- 不把 `SlippageModule`/`FeeModule` 做成 broker policy（成本模型，不是撮合/准入
  语义）；
- 不把 `OrderStore.pending_orders` 整体迁到 `BrokerStore`；
- 不接管 flow scheduler。

## 阶段 0：清理死选项（先决条件，必须在阶段2之前做完）

`OrderExecutionModule.matching_model` 字段声明的 `bar_volume_limited` 选项没有任何
代码分支处理它（全仓库搜索确认，测试和前端也都没有引用它），是历史遗留的死选项。
**建议直接从 `options` 元组里删除这一项**，而不是事后把它接到
`LiquidityModule`——因为"按成交量截断"这件事已经由 `LiquidityModule.
liquidity_mode=volume_participation` 干净地实现了，没必要在 `matching_model` 上
再留一条通往同一效果的死路，那只会让未来的 `matching_policy` selector 设计更混乱。

- 改动文件：`tools/testers/backtest/modules/order_execution.py`（删掉
  `("bar_volume_limited", "按 bar 成交量限制")` 这一行）。
- 验证：`grep -rn "bar_volume_limited"` 应该只剩这个计划文档本身和 ADR 里的引用。
- 回归：`pytest tests/backtest/native/test_order_execution.py -q`（当前无用例覆盖
  这个选项，预期无影响）。

## 阶段 1：BrokerModule 骨架（不改变行为）

新增 `tools/testers/backtest/modules/broker.py`：

- `class BrokerModule(ExecutableModule)`：只注册 policy selector 字段（见下），
  暂不接入任何 flow 的实际计算逻辑。
- `class NativeBroker`：一个纯数据/纯函数对象，根据 selector 字符串返回对应的
  callable policy（先实现 selector → callable 的映射表，policy 函数体本阶段可以
  先原样照抄现有模块里的私有函数，不必去改调用方）。
- `class BrokerStore`：`broker_by_strategy: dict[Strategy, NativeBroker]` 这类
  运行期状态容器。
- `BrokerRegistry`：用于注册/查找 `CustomBroker`（阶段1只需要能注册
  `NativeBroker` 自己）。
- `broker_for(run_state, strategy) -> NativeBroker`：查 `BrokerStore`，没有则用
  当前 strategy config 的 selector 字段构造一个并缓存。

字段与默认值（对应 ADR 表）：

| selector | 默认值 | 映射自 |
|---|---|---|
| `broker_model` | `native_broker` | 新概念 |
| `cancel_policy` | `replace_pending_same_product` | `GroupMembershipModule._schedule_order_execution` 现有行为 |
| `order_validity` | `next_signal` | 同上 |
| `matching_policy` | `next_bar_open_full_fill` | `OrderExecutionModule.matching_model` |
| `accept_policy` | `always_accept` | 现状（`reject_reason` 从未被赋值） |
| `cash_policy` | `rescale_buy_orders` | `LedgerCashConstraintModule._constrain_to_ledger_cash` |
| `min_lot_policy` | `floor_to_lot` | `PositionSizingModule.quantity_rounding_policy`（**不是 none**） |
| `fill_cap_policy` | `no_cap` | `LiquidityModule.liquidity_mode`（ADR 首版遗漏，本计划补上） |
| `price_band_policy` | `ignore` | 现状（无涨跌停逻辑） |
| `order_state_model` | `simple_filled_rejected_cancelled` | `OrderStatus` 枚举的终态子集 |

- 回归：本阶段不改任何现有模块的调用路径，跑一遍全量
  `pytest tests/backtest/ -q` 确认零变化（新文件只是新增，没有被引用）。

## 阶段 2：注册字段 + `resolve_broker` flow

- `BrokerModule.fields` 补齐 `FieldDefinition`（`public=True`，参考
  `PositionSizingModule`/`LiquidityModule` 现有字段的 `editor="select"`
  写法，`visible_if={"engine_mode": ("custom",)}` 之类的可见性规则待定，先不
  暴露给非 custom 引擎模式，避免过早在前端出现新 tab）。
- 新增 `resolve_broker: Flow`，`phase=Phase.PRE_REPLAY`，`inputs=()`，
  `outputs=()`（副作用是往 `BrokerStore` 里写，不经过 FieldRef），
  `compute=lambda account, ctx: _resolve_broker(account, ctx)`，为每个
  `ctx.active_strategies` 构造并缓存一个 `NativeBroker`。
- 注册到 `tools/testers/backtest/modules/registry.py`。
- 回归：`pytest tests/backtest/ -q` 全量，确认新增的 flow 不改变任何现有输出
  （这一步只是"构造好 broker 放在那"，还没有任何模块去调它）。

## 阶段 3~7：逐模块切换调用方（一个模块一个 commit，方便单独回滚）

每个模块的切换都遵循同一模式：把模块内部原来直接计算的私有函数，改成"读取
`broker_for(account, strategy)` 上对应的 policy，再调用它"，模块自身只保留
"何时调用 policy"（flow 编排、字段读取、写回 ctx/ledger），不再自己判断
"怎么算"。

### 3. `GroupMembershipModule.schedule_order_execution` → `cancel_policy`/`order_validity`（撤单与订单有效性）

- 现有逻辑（`group_membership.py:350` `_schedule_order_execution`）里"同
  `(strategy, instrument)` 的 stale pending order 标记 CANCELLED"这部分，改为调用
  `broker.cancel_policy(stale_order, new_order, ctx.timestamp)` 返回布尔值。
- 回归：`pytest tests/backtest/native/test_group_membership.py tests/backtest/native/test_step3_wiring.py -q`。

### 4. `OrderExecutionModule` → `matching_policy`（撮合策略）

- `_resolve_execution_price` 改为调用 `broker.matching_policy(order, price_table)`
  返回成交价，而不是硬编码 `_execution_price_at`。
- 回归：`pytest tests/backtest/native/test_order_execution.py -q`。

### 5. `PositionSizingModule` → `min_lot_policy`（最小手数策略）

- `_round_to_lot_sizes`/`_round_one` 的取整算法迁到 broker 的
  `min_lot_policy(quantity, lot_size)` callable，模块只保留字段读取和写回
  `OrderBookModule.deltas`。
- **必须同时验证 `nearest_lot` 非默认选项**，不能只测 `floor_to_lot`。
- 回归：`pytest tests/backtest/native/test_position_sizing.py -q`。

### 6. `LiquidityModule` → `fill_cap_policy`（成交上限策略）

- `_cap_to_liquidity` 迁到 broker 的 `fill_cap_policy(quantity, participation_rate,
  volume)`。
- **必须同时验证 `volume_participation` 非默认选项**（默认是 `no_cap`/`infinite`，
  容易只测默认值就漏掉这条）。
- 回归：`pytest tests/backtest/native/test_fee_slippage_liquidity_cashconstraint.py -q`。

### 7. `LedgerCashConstraintModule` → `cash_policy`（现金策略）

- `_constrain_to_ledger_cash` 里"按比例缩买单"的部分迁到 broker 的
  `cash_policy(orders, available_cash)`。
- 回归：`pytest tests/backtest/native/test_fee_slippage_liquidity_cashconstraint.py -q`。

### 8. `OrderLifecycleModule` → `accept_policy`/`order_state_model`（接收策略与订单状态模型）

- `_finalize_order` 改为调用 `broker.accept_policy(order)` 决定 FILLED/REJECTED，
  `reject_reason` 管子已存在，直接复用。
- 回归：`pytest tests/backtest/native/test_order_lifecycle.py -q`。

## 阶段 9：CustomBroker 注册路径

- `BrokerRegistry.register(broker_id, broker_or_policy_overrides)`，CLI / factor
  workspace 通过 id 引用，不接受任意 callable（安全边界，ADR 已定）。
- Custom broker 允许只覆写部分 policy，未覆写字段落回 `NativeBroker` 对应
  callable——用一个"覆盖字典 + 默认字典合并"的简单实现即可，不需要继承链。

## 阶段 10：全量回归 + 收尾

- 全量跑 `pytest tests/backtest/ -q`，确认这份计划开始前后失败用例集合完全一致
  （当前分支已知的 26 个失败属于无关的 `allocation_policy` 问题，作为基线）。
- 补一组"策略只切 broker selector、其他配置不变"的对照测试（新测试文件
  `tests/backtest/native/test_broker_module.py`），逐个 policy 维度对比切换前后
  产生的 `Order`/`EventDraft` 序列完全一致。
- 更新本计划状态为"已完成"，并在 ADR-028 顶部状态行加一条完成日期。

## 风险与回滚

- 每个阶段是独立 commit，任一阶段发现行为漂移，直接回滚该 commit，不影响已完成
  的前序阶段（因为切换是模块级别的，互相没有共享状态之外的耦合）。
- 阶段 0（删除死选项）理论上零风险，但仍先做、先跑测试，避免和后面的重构混在
  一起排查。
- 最大风险点是阶段 5/6（`min_lot_policy`/`fill_cap_policy`）——已确认
  `test_position_sizing.py::test_nearest_lot_rounds_to_closest` 和
  `test_fee_slippage_liquidity_cashconstraint.py`（两处 `volume_participation`
  用例）已经覆盖非默认分支，迁移时这两个文件不用先补测试，直接作为回归基线。
