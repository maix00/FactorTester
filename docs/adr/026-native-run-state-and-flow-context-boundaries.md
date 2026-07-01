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

### BacktestRunState

`BacktestRunState` 是整个 native backtest run 的长生命周期容器。它可以持有：

- strategy registry：`strategy_configs`
- ledger store：`ledgers`
- result store：`results`
- runtime info sink / rows
- 必须跨 PRE_REPLAY、PER_EVENT、POST_REPLAY 存活的大型 store 或缓存

`BacktestRunState` 不应作为任意模块中间变量的动态属性容器。

### FlowContext

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
