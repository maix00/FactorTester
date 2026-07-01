# ADR-027：OrderFlow Ledger 与 Snapshot 的边界

- **日期**：2026-07-01
- **状态**：已接受
- **决策者**：FactorTester 团队

---

## 背景

Native backtest 的 snapshot overlay 已能展示某个事件时间片上的持仓、target、现金、
总资产、保证金、市值等状态。但用户还需要回答另一类问题：

- target 如何变成 order；
- 同一时间的买卖如何抵消或被现金约束缩放；
- 最小手数、流动性、滑点、手续费分别改了什么；
- 订单为什么成交、拒绝、取消；
- 账本现金、持仓、费用是如何被每笔订单改变的。

这些问题不是“状态矩阵”问题，而是“订单生命周期流水”问题。如果继续把每笔 order
细节塞进 snapshot 矩阵，矩阵会变宽、变慢，并且混淆状态视图与过程审计。

行业实现通常也把两者分开：

- Zipline 使用 blotter 管理 open orders、transactions、commission/slippage 处理；
- Backtrader 把 order creation/execution、broker、commission/slippage 作为订单执行链；
- RQAlpha 暴露 order/trade/account 等事件，订单与成交是独立事件流；
- 更微观的 order flow/盘口研究可以作为未来数据源能力接入，但不应和 portfolio
  snapshot 混在同一个矩阵里。

## 决策

新增 `OrderFlowStore` / `OrderFlowModule`，把订单过程作为 native run 的独立流水：

- snapshot overlay 只回答“这个时间片组合处于什么状态”；
- orderflow overlay 回答“这个时间片每笔订单如何产生、调整、成交/拒绝，以及如何影响账本”；
- 各模块只记录自己负责的步骤：
  - `OrderBookModule`：构造订单；
  - `PositionSizingModule`：数量取整；
  - `LiquidityModule`：流动性截断；
  - `LedgerCashConstraintModule`：现金约束缩放；
  - `SlippageModule`：有效成交价格；
  - `FeeModule`：手续费；
  - `LedgerModule`：现金/持仓账本更新；
  - `OrderLifecycleModule`：成交、拒绝、取消终态。

`OrderFlowStore` 是 run-level store，因为它跨多个 flow 和事件存活，并服务于后续懒加载
overlay、CLI 审计、跨回测框架结果比对。它不是旧 snapshot helper 的扩展字段。

## 结构

每条 orderflow record 至少包含：

- `order_id`
- `strategy_id`
- `timestamp`
- `step`
- `label`
- `product`
- `quantity`
- `intent_quantity`
- `status`
- `effective_price`
- `fee_cost`
- `reject_reason`
- `details`

未形成 order 前的步骤，例如数量取整、流动性 cap，可以记录为 strategy-level step，
`order_id` 留空，`details` 中保留产品级 before/after。

## 后果

### 正面影响

- snapshot 保持轻量、可扫读；
- orderflow 可以懒加载，不拖慢普通状态查看；
- 每个模块负责自己的审计片段，便于控制变量测试；
- 非 native 框架可以把自身 blotter/order/trade 结果转换成同一 orderflow 视图，用于比对。

### 权衡

- 第一阶段只记录 native 主链，不立即重写前端 snapshot UI；
- 当前 orderflow 记录粒度是事件级，不是盘口队列级；
- 如果未来接入真实 order book / queue position，需要新增微观结构数据源和撮合模块，
  但仍挂在 orderflow overlay，而不是 snapshot 矩阵。

## 参考

- Zipline SimulationBlotter / blotter order lifecycle
- Backtrader order creation/execution、commission/slippage、order history
- RQAlpha order/trade/account event model
