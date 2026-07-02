# ADR-030：外部回测框架的执行桥（非 native 引擎不进 native event queue）

- **日期**：2026-07-02
- **状态**：已接受，实施中
- **决策者**：FactorTester 团队

---

## 背景

`run_backtest_task`（`engines/native/backtester.py`）是 `FactorTester.dispatch("backtest")`
的唯一入口。当前它对非 native 引擎直接抛 `NotImplementedError`，错误信息里已经写明
方向："must run through its own ExecutableModule/worker bridge instead of falling
back to native"。

同时仓库里已经存在但**只有测试在用**的一整套 worker 基础设施：

- `engines/workers/contracts.py`：版本化 JSON 协议（`WorkerRequest`/`WorkerResponse`）；
- `engines/workers/dispatcher.py`：每个框架一个隔离 conda 环境的子进程
  （GTHT-backtrader / GTHT-qlib / GTHT-zipline / GTHT-rqalpha），支持超时、取消、
  以及 stderr 上的 `GTHT_PROGRESS` 行式进度流；
- `engines/workers/entrypoint.py`：worker 侧单请求入口，stdout 保留给协议 JSON；
- `engines/workers/runners/{backtrader,qlib,zipline}.py`：目标权重回放与分组策略
  回放两种 operation，返回 portfolios/equity_curve/position_curve/execution_trace
  等与 native 相同形状的结果（rqalpha runner 尚未实现）；
- `engines/adapters/frameworks.py`：能力声明模型（`FrameworkCapabilities` /
  `CapabilityReport`），`FactorFrameworkAdapter.prepare` 会对无法表达的能力显式
  抛 `UnsupportedFrameworkPlan`；
- `engines/adapters/{backtrader,qlib,zipline}/factor.py` + `factor_step.py`：
  FactorExpr 在框架回调粒度上的执行适配（`PrecomputedFactorSource` /
  `IncrementalFactorSource`）。

缺的是把两边接起来的桥：production 链路（前端字段值 → `BacktestRunState`）到
worker 链路（JSON payload）之间没有翻译层，worker 的进度流也没有接到前端
SSE 流程图/进度条（`ProgressSink` 协议）。测试里的 payload 全是手写的。

## 决策

### 1. 路由：`run_backtest_task` 是唯一分叉点

```text
tester.dispatch("backtest")
  └── run_backtest_task(run_state, ...)
        ├── engine == "native"  → 现有路径：FlowRegistry + EventQueue + run()
        └── engine != "native"  → run_framework_backtest_task(...)（新桥）
              不构造 EventQueue，不注册任何 native Flow —— 框架自己跑自己的循环
```

外部框架引擎**不注册 native event queue**。native 的 Flow/EventQueue 体系只为
native 引擎服务；桥是一段顺序执行的函数（翻译 → dispatch → 收集），不是伪装成
Flow 的编排。

### 2. ExecutableModule 的角色：定义层，不是执行层

`EngineModule.engine` 字段（native/backtrader/qlib/zipline/rqalpha）仍是唯一的
引擎选择入口；所有 ExecutableModule 的 `fields`（费用、滑点、流动性、换月、
资金……）仍是**字段定义与前端 manifest 的唯一来源**。桥消费的是
`StrategyConfig.field_values`（`strategy_config_builder` 已经把前端扁平字典
桥接成 FieldRef 键的值），不再发明第二套字段体系。

### 3. 字段值翻译：声明式映射表 + 能力拒绝

新增 `engines/workers/translator.py`：

- `translate_strategy_config(config: StrategyConfig, framework: Framework) ->
  dict`：把 FieldRef 值翻成 runner 方言（`fee_rate`、`slippage_mode`、
  `slippage_bps`、`liquidity_mode`、`participation_rate`、`initial_capital`、
  `execution_timing`、`execution_delay_bars`、`margin_*`……——即
  `runners/common.py` 的 `parse_*_input` 已消费的键）。
- 映射表是数据不是代码分支：`(FieldRef, worker_key, value_mapper)` 三元组列表。
- **不静默忽略**（ADR-024 的约束）：框架无法表达的字段值，翻译器要么显式映射到
  框架托管的等价默认并记录 `setting_fallback_diagnostics`，要么抛
  `UnsupportedFrameworkPlan`。判断依据是 `frameworks.py` 的能力声明。

### 4. 因子翻译：复用 FactorSource 双形态

- `factor_mode = precomputed`（或 auto 判定为可向量化）：FactorExpr 在 native 侧
  批量求值 → 分组 membership 张量 + signal_updates 掩码进 payload（
  `parse_group_strategy_input` 已消费）。这满足 ADR-024 的"membership 必须由同一
  FactorExpr 结果生成"。
- `factor_mode = incremental`：`compile_streaming_factor` 产出可移植的
  `StreamingFactorPlan`，包进 `IncrementalFactorSource`，由框架内的
  `{Backtrader,Qlib,Zipline}FactorAdapter` 在框架自己的 bar 回调里逐步执行。
  注意 `factor_step.py` 里 `MarketSlice`/`ProductPrice` 因 issue-114 重写被删成
  stub —— 增量因子进框架前必须先修复该 stub（本 ADR 实施的第二阶段，先做
  precomputed 路径）。
- 能力检查走现有 `FactorFrameworkAdapter.prepare`，不重复造。

### 5. 市场数据：native 侧装载一次，序列化进 payload

桥直接调用 `MarketDataModule` 的装载函数（消费 `run_state.market_data_request`），
不经过 queue。产出 payload 的 `timestamps`/`instruments`/`prices`/`volumes`/
`market_rules`（lot_sizes/multipliers/margin_ratios 的时变矩阵，
`runners/common.py::_parse_rule_matrix` 已消费）。

### 6. 进度：GTHT_PROGRESS → ProgressSink → 前端流程图

- 桥在开始时向 `activity_sink.emit_activity_manifest` 发一份**框架版三阶段
  manifest**（沿用 native 的 `pre_replay`/`event_replay`/`post_replay` 阶段键与
  中文标签：翻译准备/框架回放/结果收集），前端流程图组件零改动即可显示。
- dispatcher 的 `progress` 回调（解析 worker stderr 的 `GTHT_PROGRESS` JSON 行）
  转发为 `activity_sink.emit_signal_progress(completed=, total=,
  phase="event_replay")` —— 进度条实时前进。
- 取消复用 dispatcher 已有的 `cancel_event` → `BacktestCancelled` 链。

### 7. 结果收集：runner 返回形状已经与 native 对齐

runners 已返回 `{"engine", "portfolios": {id: {equity_curve, position_curve,
notional_curve, margin_curve, execution_trace, ...}}, "target_trace",
"strategy_diagnostics", "event_count"}`。桥只需把它包进与 native
`run_backtest_task` 相同的 `execution` dict（`engine_result`/`group_owner`/
`settings_by_strategy`/`payload`），`_serialize_event_execution` 及其后的
snapshot/detail 链路零改动。事后结果字段即 `WorkerResponse.result`；实时结果字段
即 `GTHT_PROGRESS` 行（可按需扩展行内 payload，协议允许任意 JSON 键）。

### 8. 一致性测试

控制变量测试从"手写 payload 调 dispatcher"（现 `test_framework_workers.py` 的
模式）升级为"同一份 `resolved_settings_by_alias` + 同一份市场数据，分别经
`run_backtest_task`（native）与桥（各框架）"，断言：

- 目标权重序列一致（`target_trace`）；
- 等价能力下 equity curve 逐点一致；框架能力有差异的维度（如 backtrader 的
  partial fill 语义）按 `CapabilityReport` 声明豁免，豁免必须显式列出而不是
  比较时悄悄放宽容差。

## 后果

### 正面

- 前端一套字段、五个引擎；引擎差异集中在翻译器与能力声明，不散落在路由层；
- worker 基础设施从"只有测试在用"变成 production 路径，测试模式与生产模式一致；
- 前端流程图/进度条对外部框架开箱即用（同一 ProgressSink 协议）；
- CLI（ADR-024 的方向）可以直接复用桥：同一翻译器、同一结果形状。

### 权衡

- 第一阶段只做 precomputed 因子路径；增量因子进框架被 `factor_step.py` 的
  issue-114 stub 阻塞，作为第二阶段（修 stub → 接 IncrementalFactorSource）。
- rqalpha runner 尚不存在，桥对 rqalpha 会在能力检查处显式失败，而不是假装支持。
- 每框架一个 conda 子进程的启动开销（秒级）保留——隔离优先于速度，与
  dispatcher 现有设计一致。

## 实施记录（2026-07-02）

### 每个 runner 都是真事件驱动回放，不是循环里调批量函数

`run_group_strategy` 对三个已实现框架都是真正的逐 bar 回放，用框架自己的
组件，不是"算好整段轨迹再包一层"：

- **backtrader**：真 `bt.Cerebro` + `_GroupMembershipStrategy(bt.Strategy)`，
  target 在 `next()` 回调里逐 bar 计算，撤单走 `self.cancel(previous)`，
  成交走 Backtrader 自己的 broker/order 生命周期。
- **qlib**：真 `qlib.backtest.position.Position`（`_SignedPosition` 扩展支持
  做空）+ `Order`，逐 bar mark-to-market、`position.update_order` 成交。
- **zipline**：真 `zipline.finance.ledger.Ledger` + `Transaction`，逐 bar
  `position_tracker.update_position` 估值、`ledger.process_transaction`/
  `process_commission` 成交入账。

三者都不再共享原先"backtrader/zipline 函数体字节级相同"的手写纯 Python 循环；
那份逻辑抽成 `runners/reference.py`（框架无关的参考实现），只用于
`test_framework_consistency.py` 的 in-process 一致性基线（不需要 conda 环境
即可验证 worker 回放语义本身），不再是任何生产 runner 的实现。

### 事件顺序对齐 ADR-029：SIGNAL 定量、ORDER 成交

`reference.py` 和三个真实 runner 都遵守 ADR-029 的顺序：target 在 SIGNAL bar
用该 bar 的价格/权益定量（含现金缩放、手数取整），成交发生在到期的 ORDER bar
（`execution_timing=next_bar` 时延后 `execution_delay_bars` 个 bar；
`same_bar` 时当bar成交）。`reference.py` 修正前的版本在成交 bar 才定量，是
native 已经修过的同一类顺序漂移，被一致性测试量出来后一并修掉。

### Broker policy 走 ADR-028，不是另起一套字段

`runners/common.py` 新增 `BROKER_POLICY_DEFAULTS`（与 ADR-028 的 NativeBroker
默认字段表完全一致）+ `require_broker_policies()`。每个 runner 在回放开始前
调用它校验，无法表达的 selector 显式抛错，不静默降级：

- `cancel_policy=replace_pending_same_product`、
  `order_validity=next_signal`：backtrader 用 broker 撤单，qlib/zipline/
  reference 用"到期 pending 队列替换"实现，语义相同。
- `matching_policy=next_bar_open_full_fill`：backtrader `coc=False`；
  qlib/zipline/reference 固定用到期 bar 的开盘价。
- `min_lot_policy=floor_to_lot`：三个 runner 都通过
  `target_quantities`/`_backtrader_executable_target_sizes`/
  `_zipline_executable_deltas`/`_qlib_executable_deltas` 向下取整到
  `lot_sizes` 矩阵。`nearest_lot` 目前 worker 侧不可表达，翻译层
  （`translator.py`）直接抛 `UnsupportedFrameworkPlan`，不是悄悄退化成
  floor。
- `cash_policy=rescale_buy_orders`：`executable_deltas`/各框架专属版本按比例
  缩买单，从不拒单。
- `fill_cap_policy`：`no_cap`（默认）或 `volume_participation`（backtrader
  `FixedBarPerc` filler；qlib/zipline/reference 用
  `capacity_limited_deltas`），是 ADR-028 首版遗漏、审计后补上的维度，
  `translator.py` 从 `LiquidityModule.liquidity_mode` 读取。

### 意外发现并修复：native 的手数取整从未真正生效

写一致性测试时发现 `PositionSizingModule._round_to_lot_sizes` 读的是
`ctx.get(MarketDataModule.lot_sizes, {})`——但 `lot_sizes` 只在 PRE_REPLAY 的
`_publish_raw_market_data` 里 `ctx.set()` 过一次，PER_EVENT/SIGNAL 用的是全新
的 `FlowContext`（自己的空 `_values`），所以这个读取从来都拿到默认空字典，
`quantity_rounding_policy` 不管配成什么，取整从未真正执行过。改成从
`market_data_store_for(state).raw_input`（持久化在 `state` 上，不是 ctx-scoped）
读取，修好了这个此前一直存在、和本 ADR 无关但被一致性测试量出来的 bug。

## 参考

- ADR-018（事件运行时）、ADR-022（因子执行后端）、ADR-024（模块所有权与
  RQAlpha 适配边界）、ADR-028（Broker policy 边界）、ADR-029（Flow 顺序与
  RunState 命名）
- `tools/testers/backtest/engines/workers/`、`engines/adapters/`
