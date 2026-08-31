# ADR-026：Native BacktestRunState 与 FlowContext 的状态边界

- **日期**：2026-07-01
- **状态**：已接受
- **决策者**：FactorTester 团队

---

## 背景

Native event-driven backtest 已经把回测拆成多个 `Flow`。每个 `Flow`
声明 `inputs` / `outputs`，并通过 `FlowContext` 在同一阶段或同一事件
batch 内传递字段值。同时，旧实现中大量模块仍直接写入原 `AccountState`
上的动态属性，例如行情缓存、预计算因子表、期限结构映射和运行提示。

这导致两个问题：

1. 原 `AccountState` 名字暗示它只管理账户/账本，但实际承担整个回测运行容器。
2. 直接写 run 容器会绕过 `Flow.inputs` / `Flow.outputs`，让字段依赖、进度
   manifest 和后续审计无法准确表达真实数据流。

## 决策

将原 `AccountState` 重命名为 `BacktestRunState`，并明确 `BacktestRunState` 与
`FlowContext` 的职责边界。

### 回测运行状态（BacktestRunState）

`BacktestRunState` 是整个 native backtest run 的长生命周期容器。它可以持有：

- strategy registry：`strategy_configs`
- ledger store：`ledgers`
- result store：`results`
- runtime info sink / rows
- 必须跨 PRE_REPLAY、PER_EVENT、POST_REPLAY 存活的大型 store 或缓存

`BacktestRunState` 不应作为任意模块中间变量的动态属性容器。

当前允许的 run-level store 清单保持收敛：

- `RunWindowStore`：各策略正式运行窗口与全局 envelope。
- `MarketDataStore`：行情请求、装载计划、原始/因果行情表、历史字段，以及行情覆盖期提示去重状态。
- `FactorSignalStore`：预计算信号表、预计算表绑定、实时因子状态。
- `TargetStore`：各类 target-producing strategy 的已建立目标、选择签名和 target trace。
- `OrderStore`：尚未执行或待取消的订单引用。
- `EquityCurveStore`：事件回放中生成的净值/持仓缓冲。
- `TermStructureStore`：期限结构展开结果、合约元数据、通知与映射 trace。

新增 store 必须先回答“这个状态是否跨 phase/event batch 存活、是否有独立业务语义、
是否不能归入现有 store”。不能因为某个模块有临时变量就机械新增顶层 store。
例如 group membership 的成员集合缓存属于“target strategy 的选择签名”，在
`TargetStore.strategy_selection_cache` 中表达，而不是让 `TargetStore` 暴露
`membership` 这样的分组专有字段名。

### 命名迁移规则

`BacktestRunState` 是类型名与领域语义名；新增跨模块 API、文档和测试说明应优先
使用 `state` / `run_state`。但是旧 scheduler/flow callable 的统一形参
`compute(account, ctx)` 可以暂时保留，不做全仓机械替换：

- `account` 在这里是历史调用约定，表示传给 flow 的 run 容器，不再作为领域名称扩散。
- 普通 flow 内部如果只是读取 `config_for`、`ledgers` 或明确 store，改名收益很低，
  不应制造大规模无行为 diff。
- 新增代码不得继续把行情、因子、期限结构、target trace 等非账户语义写成裸
  `account.xxx` 动态属性；应写入对应 store/service 或 `FlowContext` output。
- 当某个文件正在做语义迁移时，可以顺手把局部变量改成 `state` / `run_state`，
  但必须保持小步提交，并以行为测试覆盖。

### 流程上下文（FlowContext）

`FlowContext` 是一次 flow 调度链的短生命周期字段总线：

- PRE_REPLAY / POST_REPLAY：该阶段内多个 flow 共享一个 context
- PER_EVENT：同一个 timestamp + event kind 的 batch 共享一个 context
- `ctx.set` / `ctx.get` 管理非策略字段
- `ctx.set_for` / `ctx.get_for` 管理按 strategy 分区的字段

`Flow.inputs` / `Flow.outputs` 是字段契约，不是运行时参数注入机制。生产路径
不根据声明筛选或复制 input；声明用于排序、manifest、审计和未来迁移。

### 持久化写入规则

普通 flow 不应直接写裸 `BacktestRunState` 动态属性。允许的持久写入路径是：

1. 写入 `FlowContext` 中已声明的 output 字段；
2. 通过明确的 domain store / service 方法修改长期状态，例如 `Ledger`、
   `ResultStore`、`EventQueue`；
3. 对尚未迁移的旧写法，先通过 audit warning 暴露，再逐步拆到模块 store。

## 后果

### 正面影响

- `BacktestRunState` 名称更准确，避免把行情、因子、期限结构等 run 级缓存误称为账户状态。
- `FlowContext` 成为 flow 字段依赖的唯一短期通道，便于定位未声明读写。
- 后续可以逐步迁移到少数有明确业务语义的 store / service，而不是继续膨胀
  `BacktestRunState`。
- Store 是语义边界，不是“每个模块一个文件”的机械拆分目标。轻量 store 可以和
  拥有它的模块同文件；只有共享抽象层或文件过大/循环依赖明显时，才独立成文件。

### 负面 / 权衡

- 旧模块仍存在直接写 `BacktestRunState` 的路径，不能一次性改成 strict，否则会打断
  当前回测链路。
- `Flow.inputs` / `Flow.outputs` 暂时不是强制运行时注入，因此需要 audit 模式
  辅助发现未声明读写。
- 禁止裸写 `BacktestRunState` 不意味着所有热路径都要经过通用动态路由。性能敏感路径
  应使用明确的 store/service 方法、局部变量和批量提交；contract audit 默认关闭，
  只在调试或迁移验收中启用。

## 迁移计划

1. 保留 `Flow.inputs` / `Flow.outputs` 作为契约和 manifest。
2. 默认生产路径不检查契约，避免性能回退。
3. audit 模式 warning：flow 从 `FlowContext` 读取未声明 input 或写入未声明
   output 时提示。
4. 增加 `BacktestRunState` 动态写入 audit，先 warning，后续按模块迁移。
5. 每迁移一个模块后，把对应裸写从 `BacktestRunState` 挪到拥有语义的 store/service
   或 `FlowContext` output；避免为每个细小缓存新增一个顶层 store。
6. 当主要模块迁移完成后，在 exact/debug 流程中启用 strict contract。

## 参考

- `tools/testers/backtest/engines/native/ledger.py`
- `tools/testers/backtest/engines/native/scheduler.py`
- `tools/testers/backtest/engines/native/flow.py`
