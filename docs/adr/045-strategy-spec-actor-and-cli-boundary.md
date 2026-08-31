# ADR-045: StrategySpec、Strategy Actor 与 CLI 边界

- **状态**：逐步迁移
- **日期**：2026-07-27
- **相关**：ADR-032、ADR-035、ADR-041、ADR-044

## 背景

native 回测曾把用户策略、策略回调、账本拓扑、策略簿 policy 和 Flow
适配器都暴露在相近的命名层级。作者因此需要理解多个对象，CLI 也容易把
运行时内部对象误当成配置入口。

本 ADR 定义当前唯一的用户和 CLI 路径；不提供旧运行时名称或旧 hook 名称的
兼容别名。内部 Flow 目录可以继续按实现职责组织，但不构成公共 API。

## 决策

### 用户可见的四个概念

1. **StrategyTemplate**：内置策略模板目录，例如 `group_quantile`、
   `threshold`、`long_short`。模板只定义参数 schema 和默认生命周期，不保存
   某次回测的状态。
2. **StrategySpec**：一次任务选择的策略声明。它包含 `source`（内置模板或
   Profile 中的自定义 Actor）、参数、数据需求和账户/执行配置。
3. **Strategy Actor**：用户实现的一个对象实例，而不是一份回调函数表。
   每次回测只创建/绑定一次，回放期间由 scheduler 按因果事件顺序反复调用；
   它可以在实例字段中保存上一次事件的状态，通过 `on_start`、`on_bar`、
   `on_market_feed`、`on_timer`、`on_order_event`、`on_position_event` 等回调返回 typed intent 或
   `StrategyCommand`。它不直接改变持仓、订单或现金，因此不能绕过执行层。
4. **StrategyContext**：只读市场/持仓视图和命令工厂。Actor 不拿到 scheduler、
   Flow、ledger、broker 或任意可变运行时 store 的引用。

策略源码与因子源码分属不同的工作区，不能把 Actor 放进
`custom_factors/`：

```text
personal-workspace/
├── factor-library/              # canonical factor Git repo
└── strategy-library/            # canonical Strategy Actor Git repo
profiles/<profile-id>/
├── factor-worktree/             # Profile factor source
└── strategy-worktree/           # Profile Strategy source
```

上图是当前工作区物化布局和职责示意，不是旧公共 API 的保留声明。因子库和产品库的公开入口分别以
`factortester factor-library`、`factortester product-library` 及 ADR-141 记录的 canonical API 为准；
`factor-worktree`、`custom_factors/` 等内部目录名仍属于后续一次性目录迁移范围。

`strategy-library` 使用 `.strategy_workspace/manifest.json`，Profile 的
`strategy_workspace_binding` 使用 `local-strategy-git`，与因子绑定、同步和
回滚凭据完全分离。个人 canonical 库不会因创建 Profile 自动合并；Profile
源码只在显式提交 Run 时以 `transient_run_source` 上传，Job 终止后清理。

`Strategy` 本身就是用户实现的长期存活 Actor；不再提供另一个同义构造名称。
所有可选的 `on_xxx` 回调都属于同一个 Actor 表面，
运行时通过统一的 callback registry 判断用户实际覆写了哪些回调，不再让 BAR
注册器和订单事件调度器各自维护一套判断逻辑。

`on_bar` 和 `on_timer` 的触发来源不同：前者由行情 BAR 事件驱动，后者由时钟
产生 `TimerEvent`。两者都只能返回 typed intent 或定时器控制请求；它们都不会
直接调用下游 Flow。`StrategyRuntime` 是把 Actor 回调绑定到 scheduler 的适配模块，
而 sizing、risk、execution、fee、ledger 等 Flow 仍是这些意图的唯一执行者。

订单生命周期的通用入口采用行业通用的 `on_order_event`；
`on_order_filled`、`on_order_pending_cancel`、`on_order_canceled` 等具体状态回调优先级更高，未匹配时再
回落到 `on_event`。

成交后的持仓事件同样采用“具体回调优先、通用回调回落”规则：
`on_position_opened`、`on_position_changed`、`on_position_closed` 未覆写时回到
`on_position_event`，再由其默认实现回到 `on_event`。持仓事件携带账本更新后的
不可变快照；策略不能通过快照修改账本。

`StrategyPlan` 是服务端将 `StrategySpec` 校验、补默认值、解析数据需求并
冻结后的内部计划。它不是用户要编写的策略模板，也不是另一个 hook 对象。

因此，Actor 与模板的区别是：模板是可复用的声明式算法入口，Actor 是一次
任务中真正持有运行状态的对象；模板可以生成或装配 Actor，但不会替代 Actor
的生命周期。Plan 则是把该选择冻结成执行输入，不保存策略状态。

### 命令与执行边界

用户命令只有四种基础形式：

- `submit_order(product, quantity, side)`
- `cancel_order(order_id)`
- `replace_order(order_id, quantity)`
- `close_position(product, quantity=None)`

定时器控制是另一类 scheduler 请求：`set_timer`、`set_time_alert` 和
`cancel_timer` 只管理 `TimerEvent` 的产生，不属于订单命令，也不会进入
SIGNAL 的订单意图解码器。

命令是不可变请求，不执行交易。Strategy hook adapter 在 SIGNAL Flow 中将
提交/平仓/改单转换为现有 `OrderDeltaIntent`，撤单由订单生命周期模块验证
策略归属、记录 `OrderAction`、提升 revision、更新 live/pending 索引。风险、
保证金、手续费、offset 分解、撮合和账本仍由原有 Flow 负责。

撤单或改单产生的终态不会只停留在 SIGNAL 内部：适配器会为受影响订单补发
同一时间戳的 ORDER 生命周期事件，因此 `on_order_canceled` 等 Actor 回调仍能
观察到由命令直接触发的状态变化。

订单状态通知使用独立的 `ORDER_STATUS` 事件轴。订单先进入 `SUBMITTED`，在
实际撮合机会前进入 `ACCEPTED`，再由 `ORDER` 事件处理成交、部分成交或拒绝。
状态事件不会经过价格、容量、费用、保证金或账本 Flow，避免“通知事件”被误当
成一次撮合机会；只有声明了订单状态回调的 Strategy 才会接收这条事件轴。

公开状态名与行业状态机对齐：`SUBMITTED`、`ACCEPTED`、`PARTIALLY_FILLED`、
`PENDING_CANCEL`、`PENDING_UPDATE`、`FILLED`、`CANCELLED`、`REJECTED`、
`EXPIRED`。本地等待依赖的 `BLOCKED` 仍是 native 的前置编排状态，不伪装成
交易所已经接受的订单状态。

第一阶段的 replace 语义是“撤销旧余量再提交新余量”，不承诺交易所级原子
replace。后续若需要限价、TIF、offset 或账户路由，将扩展命令字段而不是新增
一套 hook 类。

### 内部名称收敛

- `StrategyRuntime` 是策略回调的唯一运行时模块名称
- `StrategyBook` 的正式内部概念为 portfolio topology/account router，负责
  strategy 到 ledger/cash pool 的解析；不再作为用户 Actor 的父类
- `StrategyBookPolicies` 拆为内部 routing、sizing、pending-order 和 intent
  resolution services；不进入 StrategySpec schema
- Flow 仍是执行图实现，不是策略作者需要组合的对象

任何 order-routing decision 必须在“实际持仓读取 → target/delta 计算 → order
construction”之前冻结为同一 decision envelope，避免持仓来自一个 ledger、
订单却路由到另一个 ledger。

## CLI 设计

CLI 只暴露模板、策略声明和任务，不暴露上述内部类：

```text
factortester strategy list
factortester strategy template list
factortester strategy template show group_quantile
factortester strategy validate --spec strategy.yaml
factortester strategy actor inspect profiles/demo/strategy-worktree/strategies/demo/actor.py
factortester strategy actor scaffold Demo --output profiles/demo/strategy-worktree/strategies/demo
factortester profile strategy-worktree canonical-register --owner-ref <principal>
factortester run preview --strategy-spec strategy.yaml
factortester run submit --strategy-spec strategy.yaml --profile-strategy-worktree <path>
```

`strategy.yaml` 的最小形状为：

```yaml
source: builtin:group_quantile
parameters: {groups: 5, rebalance: 1d}
data: {fields: [close, volume]}
account: {ledger: default}
execution: {liquidity: infinite}
workspace: profile:demo
strategy_id: group-1
entrypoint: Demo
```

自定义 Actor 仅替换 `source`，例如 `profile:strategies/demo/actor.py`；其余
配置形状不变。`validate` 输出规范化 `StrategySpec` 和缺失能力，不输出 Flow
或 StrategyBook 的内部 repr。

`profile:` 和 `personal:` 后面的路径必须是相应工作区内的相对路径，不能包含
绝对路径或 `..`。`entrypoint` 是源码中继承 native `Strategy` 的类名；CLI 在
静态检查阶段只解析 AST，Run 执行阶段才在私有临时源码 scope 中实例化它。

## 迁移与兼容

当前 `strategy_kind` 和 target intents 仍属于配置语义，但运行时只接受
`StrategyRuntime` 的新 Flow 名称与 `StrategySpec` 入口。历史 ADR 保留原语义和
实施记录，本 ADR 作为新的用户/CLI 入口说明；不再提供旧运行时名称或旧 hook
名称的解析别名。

## 后续工作

1. 增加 `StrategySpec` schema、模板注册表和 CLI 命令
2. 将 routing/sizing/pending decision 冻结为统一 decision envelope
3. 审计账户状态事件；定时器事件已通过独立 `TimerEvent` 和 `on_timer` 公开
4. 为 custom Actor 增加命令、订单生命周期和多账户路由的端到端验收
