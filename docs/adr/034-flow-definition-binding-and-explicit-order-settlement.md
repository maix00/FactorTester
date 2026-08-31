# ADR 034：Flow 定义/绑定分离与显式订单结算

## 状态

已接受。

## 背景

原生引擎需要让 Flow 出现在前端/CLI 进度模型和跨框架审计中；同一逻辑步骤也可能在 BAR、SIGNAL、ORDER、TRADE_INTENT 或 LEDGER 事件处运行。旧 `Flow` 同时混合“步骤做什么”和“在哪里调度”，`FlowOverride` 又把费用、滑点等业务行为藏在另一个 Flow 的计算链里，导致流程图不可审计，订单结算还依赖 wrapper 注册顺序。

## 决策

引入两个显式概念：

- `FlowDefinition`：逻辑步骤身份、输入、输出、计算、所有者和默认 UI/进度描述；
- `FlowBinding`：定义绑定到的阶段、事件类型、执行顺序和可选绑定名称/描述。

`Flow(...)` 继续作为单绑定一次性步骤的便利写法，供模块逐步迁移。

移除 `FlowOverride` 的业务用途。费用和滑点改为显式 ORDER Flow：

1. `resolve_execution_price`
2. `apply_slippage`
3. `resolve_fee_cost`
4. `apply_order_fill`
5. `equity_on_order`
6. `finalize_order`

`resolve_fee_cost` 只写入 `order.fee_cost`，并执行结算前的现金约束缩放。`apply_order_fill` 执行原子账本动作：拒绝/取消处理、现金更新、持仓更新、保证金同步、订单轨迹和终态（`FILLED` 或 `REJECTED`）。`finalize_order` 不再决定状态，只记录终态；如果 ORDER 事件没有终态就离开流程，则抛错。

## 后果

- 流程图更接近用户看到的业务过程。
- 一个逻辑定义可以绑定多个阶段或事件类型而不复制计算代码。
- 绑定名称可以继续用于策略激活和既有 manifest；定义名称则暴露共享逻辑步骤。
- 费用、滑点和结算顺序通过调度顺序显式可测，不再依赖隐藏的 wrapper 组合。
- 未来定制流水线应在清晰的生命周期边界添加或替换显式 Flow，而不是包裹任意 Flow。
