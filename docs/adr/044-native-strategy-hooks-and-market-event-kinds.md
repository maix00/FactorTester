# ADR-044：Native 策略钩子与市场事件类型

- **日期**：2026-07-27
- **状态**：针对 issue #172 提议；已实现部分以当前运行时代码和测试为准
- **相关**：ADR-018、ADR-020、ADR-026、ADR-027、ADR-034、ADR-043

## 背景

Native 运行时已有因果 `EventQueue`，但公开 Strategy 对象最初只有身份信息，
自定义事件策略不得不理解 `Flow`、`FieldRef` 和订单构造图。运行时也曾把
聚合回放事件命名为 `BAR`，这不能与 L1 报价、成交或 L2/L3 委托簿更新混用。

## 决策

### 公开钩子只是适配器，不是第二个执行引擎

作者 API 可以提供可选的 `on_start`、`on_stop`、`on_event`、`on_bar`、
`on_quote`、`on_trade`、`on_book_delta`、`on_book_snapshot`、
`on_order_event` 和状态专用订单回调。适配器优先调用最具体的覆盖方法，再
回退到通用市场/事件方法。

回调只能返回有类型的目标或订单意图，不能直接修改 `Ledger`、市场数据、
订单或事件队列；返回值必须经过既有的
`SIGNAL → sizing → risk → execution → ledger` 流程。取消/替换在其不可变
动作记录接入同一命令适配器前仍是内部能力。

### BAR 不代表 L2/L3

`EventKind.MARKET_FEED` 是原始行情的调度优先级，载荷使用
`MarketFeedEventKind` 区分：

| 载荷类型 | 数据层级 | 作者钩子 |
|---|---|---|
| `QUOTE` | L1 买卖盘 | `on_quote` |
| `TRADE` | 逐笔成交 | `on_trade` |
| `BOOK_DELTA` | L2 MBP 或 L3 MBO 增量 | `on_book_delta` |
| `BOOK_SNAPSHOT` | L2/L3 快照 | `on_book_snapshot` |

`EventKind.BAR` 仍表示带有明确可见性策略的聚合 K 线。相同时间戳下，原始
行情先于 BAR 和 ORDER，等时间事件保留数据源序号。

### SIGNAL 不是定时器

`EventKind.SIGNAL` 是策略决策点，不是时钟通知。因子信号模块从对齐表或
BAR 更新后的实时状态生成它；无相关市场输入时不生成信号。定时器使用
`TimerEvent`/`EventKind.TIMER`，由调度器负责注册、取消、重复策略和确定性
排序，不能用 SIGNAL 或伪造 BAR 实现。

`BarStrategy` 只消费聚合 BAR。如果只有 L2/L3 而需要 K 线，必须由独立的
`MarketDataAggregator` 消费原始事件，按明确的收盘/可见时间发布派生 BAR；
不能把簿变化直接传给 `on_bar`，也不能在策略中偷偷读取未来簿变化。

### 数据精度与钩子形状分开声明

策略声明所需市场事件和执行能力。预检报告必须区分请求数据层级、可用
`L1`/`L2_MBP`/`L3_MBO`、成交模型、部分成交支持和剩余订单携带能力。要求
订单状态或成交后持仓轴而选定执行模型无法发出时，必须校验失败，不能静默
退化为 BAR 策略。

## 事件顺序

```text
FIELD_CHANGE
→ MARKET_FEED（quote/trade/book delta）
→ BAR
→ ORDER
→ POSITION
→ TIMER
→ SIGNAL
→ LEDGER
```

旧运行的 signal/order 精确顺序保持不变；新的原始行情只占用 BAR 之前的
优先级。钩子产生的意图以同一或更晚时间的因果 SIGNAL 入队，继续经过既有
订单流水线。

## 后果

- 简单策略只需继承 `BarStrategy` 或 `EventStrategy` 并返回意图。
- 订单状态回调只能观察生命周期；成交、费用、保证金、DMTM、取消、替换和
  剩余订单仍由账本及订单生命周期模块负责。
- 持仓事件只在成交写入账本后发出，并携带不可变快照，不暴露可变账本句柄。
- 新增市场数据格式只增加载荷类型和适配器，不增加调度阶段或重写作者代码。
