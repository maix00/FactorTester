## 回测与交易 {#backtest-and-trading}

RunSpec 冻结一次运行的产品、数据、策略、因子引用和 Nautilus 执行参数。ExecutionPlan 进一步记录运行位置、服务版本和节点上的数据 Bundle 安装匹配结果。Manager 拥有 Job 状态和结果索引；Celery/RabbitMQ 负责任务投递；Nautilus 执行节点负责回测或被授权的交易服务。

## 配置与执行位置 {#configuration-and-execution}

配置可以自动选择符合条件的执行节点，也可以让用户选择 Manager 管理的可用节点。用户的桌面本机运行时是独立的个人执行方式：它只服务本机用户，不是 Manager 节点候选，不会被远端 Manager 调度。

## 交易状态与结果 {#trading-state-and-results}

策略信号、订单、成交、费用、持仓和账户状态由 Nautilus 执行链路管理。模拟交易和实盘使用相应的 Nautilus 账户与交易适配器；券商能力缺失时，界面应明确报告未配置，不伪装为可交易状态。

运行结果应保留冻结输入、时间区间、执行节点、状态和可审计生成物。图表只是结果视图，不替代 Job 或账户状态的权威记录。
