"""FactorTester 事件驱动回测引擎 (Event-Driven Backtesting Engine)

混合架构：
- 向量化层：FactorExpr.evaluate() 一次性预计算所有因子值/returns/membership
- 事件驱动层：EventQueue (heapq FEL) + EventDrivenEngine.run() 逐期推进状态

目录结构：
- events.py      — BacktestEvent, EventCategory
- event_queue.py  — EventQueue (heapq 优先队列)
- engine.py       — EventDrivenEngine (主循环 + dispatch)
- state.py        — WorldState (equity/quantities/cash)
- clock.py        — SimulationClock (时间推进)
- context.py      — BacktestContext (预计算矩阵 + 可变数据槽)
- factors/        — EventDrivenFactor 协议 + 示例
- orders/         — OrderStrategy 协议 + 分组调仓
- models/         — FeeModel, MarginModel, LiquidityModel, ProductModel 协议
"""
