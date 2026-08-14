# Grill 173.1 — 测试结果归属

Status: accepted

## 用户修正

IC 测试应当使用专门对象表达结果，但同一份计算事实可能按不同需求投影为不同表格和图像。尚未决定该对象是否应由 `FactorTester` 自身承担；在决定前必须审计其他测试的真实结果链路。

## 当前代码事实

- `FactorTester` 是运行时任务调度薄封装；可变的产品、因子、缓存和结果状态位于 `FactorTesterState`。
- `FactorTester.results` 保存按因子索引的 `FactorRunResult`，用于当前交互状态和因子求值缓存，不是历史运行归档。
- 异步 RunSpec 为每个 Job 创建 worker-local 的隔离 `FactorTester`；Job 完成后该实例不作为结果持久化。
- IC 使用 `_ICComputeResult` 聚合多方法、多预测期和多 label offset 的临时状态，随后手工构造响应字典；只把主预测期和主 offset 的一部分结果写回 `FactorRunResult`。
- 因子序列评估读取 `FactorRunResult` 后返回自己的结果字典。
- 因子类型分析由 `FactorTypeAnalysisResult` 表达分析结果，再由 server facade 投影为传输字典。
- 分组回测已删除旧 `GroupRunResult`；真实路径由 `BacktestRunState` 和各领域 Store 保存运行状态，再投影为分组回测结果与独立 artifact。
- `BacktestResult`/`PortfolioResult` 虽有不可变 contract 定义，但当前真实 native/group 路径尚未以它们作为最终返回对象，而是组装稳定结果字典。
- Job sink 对所有分析统一执行“实时结果、持久化摘要、按需 artifact”的生命周期，但各分析交给 sink 的结果形状仍分别定义。

## 当前推论

不能把当前 `FactorTester` 实例直接当作权威测试结果：

1. 它包含运行时可变状态、锁、缓存、用户和产品对象，不是可冻结的结果值；
2. 它的生命周期可能是页面交互级，也可能是 worker-local Job 级；
3. `results` 只表达 per-factor 当前缓存，无法自然表示多组合回测、多个输出 artifact 或一次 Job 的完整身份；
4. 其他测试已经在运行上下文之外形成各自的分析结果或结果投影。

仍未决定的是：是否应建立一个所有测试共享的顶层结果协议，以及 IC 专门结果对象与该协议、`FactorTester` 运行上下文之间的关系。

## 已接受结论

1. `FactorTester` 是统一的测试执行与结果访问入口，不是某次测试结果本身。
2. 某种测试可以返回最适合其领域语义的结果对象；不要求所有测试共享同一种内部数据结构，也不要求继承重型结果类层级。
3. 测试结果只表达该次测试产生的规范化计算事实，不固化 Web 页面、CLI、表格或图像布局。
4. 表格、图像、报告以及其他按需输出由测试之外的 Renderer 生成。
5. 同一测试结果可以被多个 Renderer 使用；新增 Renderer 不应要求重跑测试。
6. “测试结果”和“呈现产物”是不同领域对象，不能继续都用 `result` 一词而不加区分。

## 下一项待 Grill

Renderer 的职责边界尚未确定：

- 只选择、排版和可视化测试结果已经包含的统计事实；
- 或者允许根据测试结果计算新的统计量和诊断。

## 行业调研（2026-07-31）

行业并没有统一采用“执行器与结果必须分离”或“一个对象包办一切”，而是存在三种主要模式。

### 模式 A：富领域结果对象

- vectorbt 的 `Portfolio` 同时保存组合模拟事实，并通过 `stats()`、指标方法和 `plot()` 按需产生不同统计表与图形；同一领域对象支持多种展示，但它不是通用实验执行器。
- statsmodels 的拟合过程返回 `RegressionResults` 等专门结果对象；`summary()` 再生成可转换为多种输出格式的 `Summary`。
- SciPy 不用一个万能结果类，而为不同统计过程返回 `TtestResult`、`PearsonRResult`、`BinomTestResult` 等小型专门结果。

适用条件：运行事实可以被一个边界清楚、相对不可变且可独立理解的领域对象完整表达。

来源：

- https://vectorbt.dev/api/portfolio/base/
- https://www.statsmodels.org/stable/generated/statsmodels.regression.linear_model.RegressionResults.summary.html
- https://docs.scipy.org/doc/scipy/reference/stats._result_classes.html

### 模式 B：执行器保留运行对象，分析器分别输出

- Backtrader 的 `Cerebro.run()` 返回策略实例；每类 `Analyzer` 挂在策略上，并由自己的 `get_analysis()` 返回实现自定义的结果结构。绘制、Writer 和 Analyzer 是不同职责。
- Zipline 直接输出 performance DataFrame，后续交给 pandas、matplotlib、Pyfolio 等生态处理。

适用条件：主要面向单进程交互式使用，用户需要运行后继续检查对象内部状态，且长期审计与跨进程持久化不是核心约束。

来源：

- https://www.backtrader.com/docu/cerebro/
- https://www.backtrader.com/docu/analyzers/analyzers/
- https://github.com/quantopian/zipline

### 模式 C：Run/Recorder 加按类型生成的 artifacts

- Qlib 用 Recorder 管理单次运行的参数、指标和 artifacts；`SigAnaRecord` 生成 IC/Rank IC 等因子分析结果，`PortAnaRecord` 生成回测结果。不同 Record Template 产生不同格式，而 Recorder 统一持久化和检索。
- MLflow 的 Run 统一记录参数、指标、时间和 artifacts，但不要求所有分析共享同一领域结果结构。
- QuantConnect LEAN 的引擎与 `BacktestResult` 分离；结果容器汇集 Statistics、Charts、Orders 和 TotalPerformance，图表和订单又有独立读取接口。

适用条件：异步或分布式执行，需要稳定运行身份、审计、选择性保留和按需读取大型结果。

来源：

- https://github.com/microsoft/qlib/blob/main/docs/component/recorder.rst
- https://github.com/microsoft/qlib/blob/main/examples/workflow_by_code.py
- https://mlflow.org/docs/latest/tracking
- https://www.lean.io/docs/v2/lean-engine/class-reference/classQuantConnect_1_1Packets_1_1BacktestResult.html
- https://www.quantconnect.com/docs/v2/cloud-platform/api-reference/backtest-management/read-backtest/charts

### 与 IC 研究最接近的做法

Alphalens 不把 IC 图表固化在 IC 计算结果中：

1. 清洗后的因子与 forward return 使用规范化 DataFrame；
2. `factor_information_coefficient()` 返回按日期和预测期组织的 IC DataFrame；
3. `create_information_tear_sheet()` 调用独立 plotting 函数生成统计表、时序图、直方图、QQ 图、月度热力图和分组图。

这证明“同一计算事实按需求产生多张表和多种图”不要求把页面展示结构写进结果对象。

来源：

- https://github.com/quantopian/alphalens
- https://github.com/quantopian/alphalens/blob/master/alphalens/performance.py
- https://github.com/quantopian/alphalens/blob/master/alphalens/tears.py

## 调研后的修正方向

FactorTester 同时具有交互式运行和异步 Job 两条路径，最接近模式 A 与模式 C 的组合：

- `FactorTester` 可以作为面向调用方的运行 facade，负责启动分析并让调用方取得结果；
- 具体运行完成后应产生一个可独立存在的结果包，而不是持久化整个 `FactorTester`；
- 结果包可以像 vectorbt 一样提供 `table(...)`、`plot(...)` 等按需投影入口；
- 服务端只持久化 Run/Job 身份、紧凑摘要和 artifact 引用，类似 Qlib/MLflow；
- IC 的多维计算事实可以使用带明确维度的分析数据集表达，表格和图像由声明式 presentation 生成；
- 不应预先要求每个测试都继承一棵重型结果类层级，也不应把所有测试塞进一个自由 JSON。

因此，上一版“共享薄协议 + 每类专门结果对象”的表述仍然过早：需要先决定统一的是结果的生命周期与访问方式，还是结果的内部数据结构。
