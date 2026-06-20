# ADR-020：流动性约束属于执行与容量分析

- **日期**：2026-06-20
- **状态**：已采纳
- **关联**：ADR-018、ADR-019

## 论证

成熟框架并不存在一个统一语义的 `LiquidityModel`：

- Zipline 的 SlippageModel 跟踪同一资产本 bar 已成交量，以历史成交量比例限制
  Fill，未成交部分保留为 open order，并用成交量占比计算价格冲击。
- Backtrader 的 filler 根据 bar volume、剩余订单量和参与比例返回本 bar 成交量。
- QLib Exchange 支持累计或当前容量、买卖方向分别配置 volume threshold，同时
  区分 impact cost 和不可交易限制。
- LEAN 的 VolumeShareSlippageModel 根据订单量/成交量计算价格冲击；成交数量由
  FillModel 负责。

参考：

- https://github.com/stefan-jansen/zipline-reloaded/blob/main/src/zipline/finance/slippage.py#L241-L312
- https://github.com/mementum/backtrader/blob/master/backtrader/fillers.py
- https://github.com/microsoft/qlib/blob/main/qlib/backtest/exchange.py#L36-L115
- https://github.com/QuantConnect/Lean/blob/master/Common/Orders/Slippage/VolumeShareSlippageModel.cs

## 决策

### 拆成四类对象

1. **TradabilityRule**：停牌、涨跌停、缺失行情、交易时段和合约状态，决定能否成交。
2. **ExecutionCapacityModel**：基于 bar volume/turnover、盘口量或外部容量，决定本次
   最多成交多少；容量不足产生部分 Fill，剩余订单继续存活或按 TIF 取消。
3. **SlippageModel**：根据方向、参与率、波动率和盘口计算成交价格，不改变目标量。
4. **CapacityAnalyzer**：研究策略规模与 ADV/turnover 的关系，只输出诊断或风险限制。

废止 `LiquidityModel.cap(desired_position)` 直接缩小目标持仓的语义。策略目标不因
本 bar 流动性不足而被改写；实际持仓通过部分成交逐步接近目标。

### 容量必须由 Broker 统一消费

同一个 execution account、产品和 bar 的所有 open orders 共享容量计数。Broker
按确定性队列处理订单，记录已消费容量；卖出和买入可以使用不同限制。没有成交量
或价格时不得默认为无限成交。

### 多策略有两种明确作用域

- **isolated evaluation**：分组和参数组合是互斥的候选策略，各自拥有独立的虚拟
  Broker、容量预算和 Ledger，但共享行情/因子计算。这是分组测试默认模式。
- **shared execution**：多个策略真实地共同交易一个账户。先由 PortfolioAggregator
  合并/净额化目标，再进入一个 OrderManager、Broker 和共享容量预算。

不得让多个独立策略直接向同一个 Broker 下单又分别声称拥有完整 bar 容量；也不得
在候选策略比较中让五个分组互相争抢流动性。

### 研究模式

研究型分组收益不模拟 Fill 时，允许使用 turnover × cost 和 participation/capacity
指标作为近似，但必须标记为 approximation，不能与事件驱动可执行结果混用。

## 后果

- 流动性成为订单生命周期的一部分，可表达部分成交、延迟成交和取消。
- 目标组合、实际持仓和未成交订单可以同时被观察，不再丢失意图。
- Broker adapter 可以映射 Zipline/Backtrader/QLib 各自的容量与滑点能力。
