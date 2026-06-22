# ADR-022：一个 Factor DSL，多个执行后端

- **日期**：2026-06-21
- **状态**：已采纳
- **关联**：ADR-004、ADR-018

## 行业依据

成熟框架把因子语义与执行方式分开：

- Backtrader 的同一 Indicator 同时支持逐 bar `next` 和批量 `once`，默认还能用
  `once_via_next` 复用逐步语义：
  https://github.com/mementum/backtrader/blob/master/backtrader/indicator.py
- Zipline `CustomFactor` 声明 inputs 与 window_length，由 Pipeline engine 调用
  `compute`；交易策略另在 `handle_data` 生命周期运行：
  https://github.com/stefan-jansen/zipline-reloaded/blob/main/src/zipline/pipeline/factors/factor.py
  https://github.com/stefan-jansen/zipline-reloaded/blob/main/src/zipline/algorithm.py
- Qlib Expression 通过 `load/_load_internal` 执行区间算子，策略通过
  `generate_trade_decision` 在每个交易 step 运行：
  https://github.com/microsoft/qlib/blob/main/qlib/data/base.py
  https://github.com/microsoft/qlib/blob/main/qlib/strategy/base.py

因此，给作者两套因子类或让事件回测强制等待完整 DataFrame 都不是合适的 Seam。

## 决策

### FactorExpr 是唯一作者 Interface

`FactorExpr.evaluate(ctx)` 明确定义为 Batch backend 入口。Incremental backend 由
compiler 把同一表达式图编译为有状态 kernel；作者不实现第二个 `evaluate_event`
方法。两种 backend 必须产生相同数值语义和同一种 `FactorSignal`。

Incremental compiler 不支持某个算子时立即抛出 `UnsupportedStreamingFactor`。
禁止在事件运行期间静默预计算完整区间，禁止降级为 Batch backend。

### 按数据依赖选择执行形态

| 因子形态 | 例子 | Batch | Incremental |
|---|---|---|---|
| 逐点 | 算术、比较、log、sign | 向量化 | 无状态 kernel |
| 有限历史 | Shift、Rolling mean/std/corr | rolling table | 有界状态 kernel |
| 递归状态 | EMA、Kalman、在线回归 | scan/向量库 | 专用常量内存 kernel |
| 同期横截面 | Rank、ZScore | axis operation | MarketSlice barrier 后计算 |
| 期限结构 | spread/slope/ratio | 日曲线批量 | 需要 contract-curve event source |
| 信号采样 | SignalAlign/session basepoint | index alignment | Calendar/Timer actor |

不允许用“先跑一次完整回放生成因子，再跑一次回测”作为递归状态、期限结构或信号
采样的默认实现；这会重复数据扫描、扩大内存，并可能让两个回放的交易日历不一致。

### 交易路径状态不是市场因子

依赖 Order、Fill、Position、Cash、Margin 或 Ledger 的值必须订阅相应事件，作为
Strategy state、Risk Module 或 Analyzer。它们不能伪装成只接收市场数据的
FactorExpr，否则 batch 预计算无法表达因果关系。

`NextReturns`、未来收益和事后 IC label 只属于 Analyzer/评价数据，禁止编译为交易
时可见信号。

### 外部框架 Adapter

每个框架拥有独立 Adapter package：

- Backtrader：`Strategy.next` 与 data line `[0]`；
- Zipline：`handle_data` 与 `BarData.current`；
- Qlib：`generate_trade_decision` 与 `Exchange.get_quote_info`。

Adapter 接受 `PrecomputedFactorSource` 或 `IncrementalFactorSource`。没有实现目标
框架 kernel 时 capability report 必须标记 extension required 或 missing，不得自动
切换成预计算信号。

## 后果

- 普通研究仍使用高吞吐量向量化计算。
- 路径相关或昂贵回放型因子可以与回测共享一次行情推进。
- Operator 的 Batch/Incremental Implementation 可独立做数值一致性测试。
- EMA、SignalAlign、期限结构等只有在专用增量 kernel 完成后才宣称支持。
