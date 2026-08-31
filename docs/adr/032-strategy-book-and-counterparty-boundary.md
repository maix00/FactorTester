# ADR-032：StrategyBook 与 CounterParty 的边界（取代 ADR-028）

- **日期**：2026-07-03
- **状态**：已接受
- **决策者**：FactorTester 团队
- **取代**：[028-native-broker-policy-boundary.md](028-native-broker-policy-boundary.md)、[ADR-128：Native Broker Policy 迁移实施计划](128-native-broker-policy-implementation-plan.md)

---

## 背景

ADR-128 的实施计划曾打算把订单行为（撤单、成交价、现金约束、终态确认……）统一收拢到一个 `BrokerModule`
暴露的 ~9 个 policy selector 后面，各执行模块改为调用 `broker_for(state, strategy).policy()`。
这是 Lean（`IBrokerageModel`）的路数——用一个 Broker 对象同时管"账户结构"和"费用/撮合模型"。

对照 Qlib 的架构（`Strategy` 生成信号、`order_generator` 把 target 变成订单且直接持有
`trade_exchange` 引用做可交易性检查、`Exchange` 只管涨跌停/停牌/成交量等微观结构约束、
`Account`/`Position` 单独管现金是否够）复核后发现：

1. Qlib 把"账户结构"（Account）和"撮合/微观结构约束"（Exchange）分得很开——这两件事在
   Lean 里被"Broker"一个词混在一起，是 ADR-028 命名混乱的根源。
2. Qlib 自己也没有建模"期货公司在交易所公开费率上加价"这件事——这是我们要解决的第三个真实
   需求，Qlib 没有现成答案。
3. `tools/testers/backtest/engines/workers/runners/common.py` 里 ADR-028 设想的 9 个
   selector，除 `min_lot_policy`（`PositionSizingModule.quantity_rounding_policy`）和
   `fill_cap_policy`（`LiquidityModule.liquidity_mode`）外，其余 7 个从未被任何模块注册成
   真实字段——`require_broker_policies` 对它们的校验永远走默认值分支，是死脚手架。

## 决策

废弃"Broker 是模型工厂"的方向。把原 `BrokerModule`/`NativeBroker` 拆成概念上不重叠的两半：

### 策略簿（StrategyBook，`tools/testers/backtest/modules/strategy_book.py`）

策略入口：注册哪些策略、每个策略可以操作哪些 `ledger_id`（账本路由）、每个策略用哪种 target
生成方式（`GroupMembershipModule` 分组 / `LongShortCompositionModule` 多空）及其参数。

- `StrategyBookModule` 字段：`strategy_book_mode`，当前默认且唯一内置值为
  `per_strategy_one_ledger`，表示每个 strategy 自动拥有一个私有 ledger。
- `StrategyBook`：运行时策略簿对象，保存 `strategy -> ledger_id(s)` 与 ledger spec。可以用
  `StrategyBook.from_dict(...)` 从声明式映射构造，也可以被子类覆写 `ledger_ids_for_strategy`、
  `ledger_id_for_order`、`provision_ledgers` 等函数。
- `StrategyBookSimple`：最小默认实现；`strategy_book_mode=per_strategy_one_ledger` 时使用它。
  不保留旧默认类名，因为 StrategyBook 不是 native 引擎专属对象。
- `FactorModule`/`ProductSelectionModule`/`RunWindowModule` 等策略级字段（`scope_policy`
  默认 `OVERRIDABLE`，不是 `LOCAL_ONLY`）天然属于 StrategyBook 的字段集合——**不新建
  "BacktestConfig"对象**，运行内共享的字段本来就该标 `scope_policy=local_only`
  （`tools/testers/settings/contracts.py`/`resolver.py` 已实现）。
- **验证结论**：账本路由（`ledger_id_for`）和订单生成（`OrderBookModule._basic_size_order`/
  `_construct_orders`）已经是通用的——两者只认 `TargetStrategyModule.target_weights`，不认
  `GroupMembershipModule` 这个具体类型；`LongShortCompositionModule` 已经是这套通用管线的
  第二个实例。"分组测试的 split_count/group_index 只是一种特殊的 strategy"这个前提已经成立，
  不需要额外抽象。唯一还没通用化的点：`strategy_config_builder._resolve_active_flow_names`
  用 `strategy_kind in {"group", "long_short"}` 硬编码二选一，`strategy_kind` 由
  `GroupTestModuleRegistry`/`LongShortModuleRegistry.parse_strategy` 各自写死——这是以后接
  第三种策略类型（例如未来的 `--strategy-book xxx.py` 自定义导入）时要打开的口子，现在只有
  两种类型，不提前为假设中的需求泛化。

### CounterParty（期货公司/经纪商条款——费用、保证金、流动性、撮合基准价）

**不是新的运行时对象**，`FeeModule`/`MarginModule`/`LiquidityModule`/`OrderExecutionModule`
的 Flow 逻辑完全不动。核实发现这套机制其实已经存在：`EngineModule.engine_mode` 的
`basic`/`auto`/`exact` 三个值本来就是三个内置的 CounterParty 预设——`FeeModule.fee_mode`/
`MarginModule.margin_mode`/`TradingRuleModule.accounting_mode`/`use_int_position` 都已经用
`default_if={"engine_mode": {...}}` 按这三个值批量填默认值；`custom` 就是"自定义
CounterParty"的开关。

新增 `EngineModule.counterparty_profile` 字段（仅 `engine_mode=custom` 时可见）。该字段可以
作为旧 per-strategy 设置入口，但进入回测前必须解析到 `ledger_id -> CounterPartyProfile`：
同一 ledger 上多个 strategy 如果给出不同 CounterParty，应报错，除非调用方显式提供
per-ledger 覆盖。`tools/testers/settings/counterparty.py` 的
`register_counterparty_profile` 把一份 `field_defaults` 拼进目标字段自己的
`default_if["counterparty_profile"]` 字典，跟现有的 `"engine_mode"` key 并列——复用
`strategy_config_builder._default_value_for_field` 已经支持"一个字段的 default_if 有多个
source_key"这个能力，不需要新的结算前展开步骤。显式设置的字段值永远优先于 `default_if`
展开（既有行为）。

### 死脚手架清理

`common.py` 的 `BROKER_POLICY_DEFAULTS`（10 key）改名为 `WORKER_EXECUTION_POLICY_DEFAULTS`，
只保留真正被使用的 `min_lot_policy`/`fill_cap_policy` 两个 key；其余 8 个从未被注册成真实
字段的 selector（`broker_model`/`cancel_policy`/`order_validity`/`matching_policy`/
`accept_policy`/`cash_policy`/`price_band_policy`/`order_state_model`）一并删除。
`broker_policies`/`require_broker_policies` 改名为 `worker_execution_policies`/
`require_worker_execution_policies`，`translator.py` 的 `_broker_policy_selectors` 改名为
`_worker_execution_policy_selectors`——这两个 selector 本质上是"跨框架执行约束翻译"（数量
取整、成交量参与率上限），跟 StrategyBook（账本路由）、CounterParty（商业条款）都无关，是
第三个独立的、范围窄得多的概念，不需要单独命名成"broker"什么的，维持现在的具体描述性命名。

## CLI/Web 命名（大部分推迟）

- 代码里没有找到字面意义上的 `--engine_mode` CLI flag（只有 web 表单/JSON payload 里的
  `engine_mode` 字段键）。内部 FieldRef key `engine_mode` 本轮不改名（改名会牵连每个模块的
  `editable_if`/`default_if` 字面量和全部测试，跟本次范围不成比例）；如果/当有独立 CLI
  入口把这个字段暴露成 flag，展示层名字可以叫 `--counterparty_mode`，不涉及内部字段。
- `--counterparty xxx.py`（导入自定义 CounterParty 行为）、`--strategy-book xxx.py`（直接
  导入完整策略簿，含账本分配和自定义决策融合/层级约束机制）**明确推迟**。已确认代码里有可复用的
  "动态导入用户 .py 文件"先例（`tools/data/sqlite/factor_metadata.py:73`、
  `tools/data/field_history.py:1541` 的 `importlib.util.spec_from_file_location` +
  `exec_module`），到时候照这个模式写。

## 后果

### 正面影响
- "Broker"这个词不再同时表示两件不同的事，StrategyBook（账本路由）与 CounterParty（商业
  条款）语义边界清晰，不会重蹈 Lean 式命名混乱。
- CounterParty 复用 `engine_mode` 已经在跑、已经测试过的 `default_if` 机制，没有引入新的
  结算通路，`resolve_group_settings`/`build_strategy_configs` 一行不改。
- 清理了 8 个从未使用过的 policy selector 死脚手架。

### 权衡
- `EngineModule.counterparty_profile` 和 `StrategyBookModule.strategy_book_mode` 分属两个不同
  模块。前者是交易条款入口，最终要落到 ledger；后者是账本拓扑入口，不能承担 CounterParty
  解析职责。
- `strategy_config_builder._resolve_active_flow_names` 的 `strategy_kind` 二选一硬编码保留
  为已知的未来扩展点，没有解决，只是记录在案。

## 参考
- [Lean IBrokerageModel](https://github.com/QuantConnect/Lean/blob/master/Common/Brokerages/IBrokerageModel.cs)
- [Qlib Exchange](https://github.com/microsoft/qlib/blob/main/qlib/backtest/exchange.py)
- [Qlib WeightStrategyBase/order_generator](https://github.com/microsoft/qlib/blob/main/qlib/contrib/strategy/signal_strategy.py)
- [Backtrader Broker](https://www.backtrader.com/docu/broker/)
- [QuantConnect Cashbook](https://www.quantconnect.com/docs/v2/writing-algorithms/portfolio/cashbook)
