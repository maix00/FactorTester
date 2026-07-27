# ADR-045: StrategySpec、Strategy Actor 与 CLI 边界

- **状态**：逐步迁移
- **日期**：2026-07-27
- **相关**：ADR-032、ADR-035、ADR-041、ADR-044

## 背景

native 回测曾把用户策略、策略回调、账本拓扑、策略簿 policy 和 Flow
适配器都暴露在相近的命名层级。作者因此需要理解多个对象，CLI 也容易把
运行时内部对象误当成配置入口。

本 ADR 不删除旧对象。旧对象在迁移期间继续提供兼容入口，但新的用户和
CLI 接口必须只有一条清晰路径。

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
   `on_market_feed`、`on_order_event` 等回调返回 typed intent 或
   `StrategyCommand`。它不直接改变持仓、订单或现金，因此不能绕过执行层。
4. **StrategyContext**：只读市场/持仓视图和命令工厂。Actor 不拿到 scheduler、
   Flow、ledger、broker 或任意可变运行时 store 的引用。

`StrategyActor` 是 `Strategy` 的新公共名称；`Strategy` 仍作为兼容构造入口。
两者不是两个运行时对象。所有可选的 `on_xxx` 回调都属于同一个 Actor 表面，
运行时通过统一的 callback registry 判断用户实际覆写了哪些回调，不再让 BAR
注册器和订单事件调度器各自维护一套判断逻辑。

订单生命周期的通用入口采用 `on_order`；旧的 `on_order_event` 继续作为兼容别名，
而 `on_order_filled`、`on_order_canceled` 等具体状态回调优先级更高。

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

命令是不可变请求，不执行交易。Strategy hook adapter 在 SIGNAL Flow 中将
提交/平仓/改单转换为现有 `OrderDeltaIntent`，撤单由订单生命周期模块验证
策略归属、记录 `OrderAction`、提升 revision、更新 live/pending 索引。风险、
保证金、手续费、offset 分解、撮合和账本仍由原有 Flow 负责。

撤单或改单产生的终态不会只停留在 SIGNAL 内部：适配器会为受影响订单补发
同一时间戳的 ORDER 生命周期事件，因此 `on_order_canceled` 等 Actor 回调仍能
观察到由命令直接触发的状态变化。

第一阶段的 replace 语义是“撤销旧余量再提交新余量”，不承诺交易所级原子
replace。后续若需要限价、TIF、offset 或账户路由，将扩展命令字段而不是新增
一套 hook 类。

### 内部名称收敛

- `StrategyHookModule` 的正式内部概念为 `StrategyRuntime`，保留旧名作为
  兼容别名
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
factortester backtest run --strategy strategy.yaml
```

`strategy.yaml` 的最小形状为：

```yaml
source: builtin:group_quantile
parameters: {groups: 5, rebalance: 1d}
data: {fields: [close, volume]}
account: {ledger: default}
execution: {liquidity: infinite}
```

自定义 Actor 仅替换 `source`，例如 `profile:my-profile/strategy.py`；其余
配置形状不变。`validate` 输出规范化 `StrategySpec` 和缺失能力，不输出 Flow
或 StrategyBook 的内部 repr。

## 迁移与兼容

当前 `strategy_kind`、旧 target intents、`StrategyHookModule` 和
`StrategyBookPolicies` 在迁移期仍可被旧配置解析。规范化器把旧配置转换为
`StrategySpec`，运行时继续使用现有 Flow。新测试优先验证新名称和命令，旧测试
验证兼容别名。历史 ADR 保留原语义和实施记录，本 ADR 作为新的用户/CLI 入口
说明。

## 后续工作

1. 增加 `StrategySpec` schema、模板注册表和 CLI 命令
2. 将 routing/sizing/pending decision 冻结为统一 decision envelope
3. 将内部模块逐步改名并保留导入别名
4. 为 custom Actor 增加命令、订单生命周期和多账户路由的端到端验收
