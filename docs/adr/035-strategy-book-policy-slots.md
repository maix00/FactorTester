# ADR 035：StrategyBook 策略政策插槽

## 状态

已接受。

## 背景

原生回测引擎暴露了多个跨越单个策略或模块边界的决策：订单路由到哪个账本、账本允许使用多少现金、订单构造前如何调整目标差额、如何处理新信号与待处理订单冲突，以及如何合并交易决策或应用层级约束。把它们作为 `StrategyBookStore` 上互不相干的可调用对象，会让扩展面难以理解；反过来把所有默认行为放进 StrategyBook 也会混淆所有权。

## 决策

`StrategyBookStore` 拥有一个 `StrategyBookPolicies` 对象，每项策略都是明确的扩展插槽：

- `order_routing`
- `cash_availability`
- `order_sizing`
- `pending_order_conflict`
- `trade_decision_merge`
- `hierarchy_constraints`

StrategyBook 承载这些插槽，因为它们是策略/账本编排决策；默认业务实现仍由所属模块维护：

- `OrderConstructModule` 计算默认订单差额和手数；
- `OrderFlowModule` 负责待处理订单冲突的默认行为；
- 现金和保证金辅助函数负责默认可用现金行为。

策略意图与订单数量计算是两层。目标权重是 `TargetWeightIntent` 的一种格式，技术规则或事件策略也可以产生 `OrderDeltaIntent`。`OrderConstructModule` 消费意图并生成订单差额/订单；StrategyBook 可以覆盖数量或冲突行为，但不拥有默认成员选择、分组多空、技术规则或强平逻辑。

调用方应使用 `apply_order_sizing_policy`、`apply_pending_order_conflict_policy`、`available_cash_for_ledger` 等模块级辅助函数，而不是直接访问原始策略字段。

## 后果

- 数量计算不再是公共可执行模块，而是带 StrategyBook 覆盖点的订单构造内部步骤。
- 分组成员和多空是具体策略意图政策，不是订单构造的普遍前提。
- 不适合表达目标权重的策略可以直接发出 `OrderDeltaIntent`。
- 订单生命周期不单独成为 Flow；终态由产生该状态的业务动作之后的 `OrderFlowModule` 辅助函数记录。
- 新信号替换同策略同产品的未来订单仍是默认行为；更丰富的 StrategyBook 可以覆盖而不改变流程图，也不把 StrategyBook 变成回测引擎。
