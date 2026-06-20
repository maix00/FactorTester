# ADR-019：分组测试的多策略与期货资金语义

- **日期**：2026-06-20
- **状态**：已采纳
- **关联**：ADR-018 因果事件运行时

## 背景

分组测试首先是横截面因子评价方法，其目标是比较不同因子分位数组合的收益。
现有 `simulate_group_trading_book` 同时承担排序、等额分配、手数取整、手续费、
保证金、流动性和结算，并把可用资金按“保证金成本”平均分给入选品种。

这种算法不是等权分组：保证金率越低的品种会获得越大的名义敞口，因子结果会
混入交易所保证金差异。保证金是履约担保和可执行性约束，不应隐式决定策略权重。

Alphalens 的 `factor_weights` 先把组合归一化到固定 gross leverage，
`equal_weight=True` 时资产权重相等。QLib 的 `WeightStrategyBase` 也是先产生目标
权重，再由 OrderGenerator 转换为订单。期货保证金与逐日盯市属于执行和会计层。

参考：

- https://github.com/quantopian/alphalens/blob/master/alphalens/performance.py#L129-L205
- https://github.com/microsoft/qlib/blob/main/qlib/contrib/strategy/signal_strategy.py#L298-L372
- https://www.cmegroup.com/education/courses/introduction-to-futures/margin-know-what-is-needed.html
- https://www.cmegroup.com/education/courses/introduction-to-futures/mark-to-market.html

## 决策

### 一个分组就是一个策略

每个因子参数组合产生一组横截面信号；若分成五组，则创建五个独立的
`QuantileGroupStrategy`。每个策略拥有唯一 `strategy_id`、独立 `portfolio_id`、
OrderManager、Ledger 和结果。前端传入的其他组合按同样规则创建新的策略实例。

同一次 run 中所有策略共享：

- 行情事件源与 MarketState；
- 相同结构的 FactorExpr 计算和缓存；
- EventRuntime 与时钟；
- Broker 实现和静态市场规则。

策略之间不共享持仓、现金、保证金和订单生命周期。事件必须携带 strategy_id 与
portfolio_id，防止不同分组或参数组合串账。

### 分组默认等名义敞口

`QuantileGroupStrategy` 只产生目标权重。默认 `EqualNotionalSizer` 按以下方式换算：

```text
组内权重 = 1 / 有效成员数
目标名义金额 = 组合权益 × 组内权重
目标手数 = floor(目标名义金额 / (价格 × 合约乘数) / lot_size) × lot_size
```

保证金率不出现在权重和目标名义金额公式中。由于手数离散，未使用资金保留为现金。

其他分配方式必须显式命名：

- `equal_margin`：等保证金占用，会产生不同名义敞口；
- `equal_risk`：按波动率、协方差或风险预算分配；
- `factor_weighted`：按因子值归一化；
- `custom`：前端或用户策略提供目标权重。

报告必须记录 allocation policy，不能把不同语义的结果放在同一指标名下比较。

### 保证金只负责约束和会计

PositionSizer 产生目标名义敞口后，MarginConstraint 计算所需初始保证金。若超过
策略允许的 collateral/leverage：

1. 默认按统一比例缩小全部目标权重，保持组内相对权重；或
2. 由显式策略配置拒绝整个调仓。

不得按产品顺序逐个耗尽现金，也不得因为保证金率较低就提高该产品策略权重。

Ledger 分开记录 free cash、margin occupied 和 equity。期货逐日结算实现盈亏并
重置 lot mark；保证金变化只调整 free cash 与 margin occupied，不凭空改变权益。

### 手续费属于成交

手续费由 CommissionModel 根据实际 Fill 计算：

- 比例费用使用实际成交金额；
- 固定费用使用实际成交手数；
- 舍入粒度由数据源/经纪商规则明确指定；
- 开仓、平昨、平今根据被关闭 lot 的开仓交易日确定。

产品级 `use_closetoday_vec` 无法表达一次卖出同时包含平今和平昨，不能作为最终
事件模型。FIFO/LIFO/指定平仓顺序必须由交易所或经纪商执行规则决定。

### 研究模式与可执行模式

- **Research group return**：固定权重定义，直接计算 gross return；可叠加明确的
  turnover cost approximation，不模拟手数、保证金和部分成交。
- **Executable group strategy**：使用同一目标权重，通过事件运行时生成订单、
  Fill、手续费、保证金、流动性和结算。

两种模式必须分别命名并展示。研究模式用于判断因子排序能力；可执行模式用于判断
策略落地表现，二者不要求逐点相同，但目标权重语义必须一致。

## 后果

- 五分组不再是匿名矩阵的五行，而是五条可独立追踪、取消和比较的策略事件链。
- 不同参数组合可以在一次行情回放中并行运行，避免重复读取行情和计算公共因子。
- 当前按保证金现金等额买入的实现不再作为默认分组语义，需在迁移中删除或明确
  命名为 `equal_margin`。
- 平今费、部分成交和保证金不足可以在 Fill/Ledger/Risk actor 中准确表达。
