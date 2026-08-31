# ADR-031：订单数量计算流水线与结算通知

## 状态

已接受。

## 背景

原生回测引擎过去把最小手数取整和流动性参与率作为 `FlowOverride`，包在 `OrderBookModule.size_order` 外层。机械上可用，但可观察的流程图把目标权重转订单差额、手数取整、流动性上限、订单构造和现金/保证金约束等不同经济步骤压成一个节点；这不利于策略研究和快照审计。

期货每日盯市是另一类会计事件。交易所用每日官方结算价确定每日盈亏，并在需要时调整保证金。它不是策略下单，不能藏在普通 broker/accounting 逻辑里，否则现金、保证金、快照和订单流无法解释账本为什么变化。

参考资料：

- CME Group：Mark-to-Market，关于每日结算和保证金调整的说明：<https://www.cmegroup.com/education/courses/introduction-to-futures/mark-to-market>
- Backtrader：期货与现货补偿模型，把到期影响作为 broker/data-feed 行为，而非普通信号生成：<https://www.backtrader.com/docu/order-creation-execution/futurespot/future-vs-spot/>

## 决策

数量约束使用显式流水线 `Flow`，不再用 `FlowOverride` 表达独立经济步骤：

```text
size_order(raw_deltas)
  -> round_order_quantity(sized_deltas)
  -> cap_order_liquidity(deltas)
  -> construct_orders(orders)
  -> constrain_to_ledger_cash(orders)
```

中间字段是策略作用域、上下文作用域的内部字段：

- `raw_deltas`：执行约束前的目标减当前持仓；
- `sized_deltas`：完成最小手数和数量规则后的差额；
- `deltas`：订单构造前最终可执行的数量差额。

`FlowOverride` 仍可存在，但只用于不改变阶段图的装饰行为，例如给同一个成交/现金更新增加费用或滑点副作用。只要步骤有独立经济含义、输出、进度标签或审计轨迹，就必须成为一等 `Flow`。

每日盯市实现为结算通知而不是订单通知：

1. 使用交易所日历和产品交易时段解析器，在完整交易日结束后登记一条通知；
2. 使用官方结算价和历史保证金字段；
3. 将每日变动盈亏计入现金；
4. 重置下一交易日的结算基准；
5. 重新计算占用保证金；
6. 发出快照/订单流式审计记录。

如果引擎没有独立的结算事件类型，应新增该类型，而不是复用 `ORDER_NOTICE`。`ORDER_NOTICE` 表示可能产生或取消订单的通知（如移仓、强平）；结算直接改变账本，必须在进度、快照和测试中可区分。

## 后果

- 订单数量路径比原先更显式，但仍按产品数线性运行；原有覆盖链已经执行相同转换，不会增加实质运行成本。
- Flow manifest 和进度展示可以分别显示每个数量步骤。
- 快照/订单流可以分别暴露原始目标、取整数量、流动性上限和最终订单。
- 结算需要独立模块、结算基准字段和测试，至少覆盖：无持仓通知是可追踪的空操作、期货多空持仓把每日盈亏计入现金、结算后保证金更新、夜盘映射到正确交易日，以及缺少结算价/保证金字段时精确模式报错。
