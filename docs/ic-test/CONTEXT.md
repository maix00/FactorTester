# IC Testing

IC 测试领域负责产生因子与未来收益横截面相关性的规范化计算事实；表格、图像和报告由外部呈现组件按需生成。

## Language

**测试执行器（Test Runner）**:
配置并执行一种测试、返回该次测试结果的运行时对象；当前统一入口是 `FactorTester`。
_Avoid_: Result, report

**测试结果（Test Result）**:
一次已识别测试运行产生的规范化计算事实，其具体对象类型由测试领域决定。
_Avoid_: Page response, chart, report, `FactorTester`

**Renderer**:
消费测试结果并按明确请求生成呈现产物的外部组件。
_Avoid_: Test runner, result owner

**呈现产物（Presentation Artifact）**:
由 Renderer 从测试结果生成的表格、图像、报告或其他面向消费端的输出。
_Avoid_: Test result, source evidence

**Artifact ID**:
用户、UI 和公开 CLI 可请求的逻辑呈现产物类型；服务器定义其 Renderer 与 required /
supplemental Result ID 依赖，不等同于最终文件名。
_Avoid_: Result ID, artifact file name

**Result ID**:
TestModule 与 Artifact Renderer 之间使用的内部计算事实组件 ID；由 Artifact 依赖生成内部
ResultPlan，用户不能直接提交。
_Avoid_: Public output request, UI tab, artifact file name

**Flow Ref**:
Flow inputs/outputs 使用的 typed port identity；`StateRef` 与 `ResultRef` 共享其身份和
schema Interface，但拥有不同更新不变量。
_Avoid_: Runtime value wrapper, database result primary key

**State Ref**:
指向测试运行内部可重复读取和更新状态的 Flow Ref；只能在拥有该 mutable runtime 的
Lifecycle/Composite Flow 内传播。
_Avoid_: Published result, cross-Flow immutable fact

**Result Ref**:
指向一次 Job 中由唯一 provider 原子发布一次的计算事实；对应内部 Result ID，不允许二次
覆写。
_Avoid_: Mutable slot, public Artifact request

**复合 Flow（Composite Flow）**:
在统一 Flow 计划中表现为单个 provider、内部运行自己的子图或状态机并最终原子发布 outputs
的 Flow；回测生命周期是复合 Flow。
_Avoid_: A second top-level Job executor, an expanded per-bar Result DAG

**测试 Flow 组合（TestFlowComposition）**:
一种测试执行中必选 Flow、可用结果 provider 与 Artifact 依赖组成的确定性组合；非执行预览
不触发该组合。
_Avoid_: UI layout, dynamically discovered plugin list

**因子求值上下文（FactorEvaluationContext）**:
一个兼容求值 batch 中一个或多个 Factor 共享的数据预载、时间轴、表达式缓存与求值结果
边界；由现有 `EvaluationBatchContext` 演进。
_Avoid_: Test result, page session, FactorTester

**表达式求值上下文（ExprEvaluateContext）**:
一棵 FactorExpr DAG 在一次递归求值中使用的内部只读执行视图。
_Avoid_: Batch manager, TestModule, Factor result store

## Relationships

- 一个 **测试执行器** 每次执行产生一个 **测试结果**
- 一个 **测试结果** 可以被零个或多个 **Renderer** 消费
- 一个 **Renderer** 可以从同一 **测试结果** 生成一个或多个 **呈现产物**
- 删除或新增 **Renderer** 不改变既有 **测试结果**
- 一个 **TestModule** 可以按需建立一个或多个 **FactorEvaluationContext**
- 一个 **FactorEvaluationContext** 为每个 Factor 根建立 **ExprEvaluateContext**
- `FactorTester` 在上述职责完成迁移后退役，不承担测试分发或结果分发
- 用户请求 **Artifact ID**，控制面据其依赖生成内部 **Result ID** 计划
- `StateRef` 只能留在拥有 mutable runtime 的 **复合 Flow** 内；复合 Flow 对外发布
  `ResultRef`
- 回测的 **复合 Flow** 必须先于所有回测指标与 Artifact 推导；其外部输入 provider 可以
  排在它之前
- 回测的 **复合 Flow** 构造一次领域 `BacktestResult` IntermediateResult；它通过固定
  resolver 提供多个基础 **Result ID**，而不是复制多份曲线或成交数据
- **Result ID** 按可消费研究事实保持细粒度；Flow 按共享输入和一次有意义的矩阵/路径计算
  保持较粗粒度，普通标量指标函数不各自成为 Flow

## Example dialogue

> **Dev:** “IC 热力图是否应当存进 `FactorTester.results`？”
> **Domain expert:** “不应当。IC 测试先产生测试结果；热力图由 Renderer 从该结果按需生成，是呈现产物。”

## Flagged ambiguities

- “结果”过去同时指计算事实、HTTP JSON、统计表和图像；现统一区分为 **测试结果** 与 **呈现产物**。
- `FactorTester.results` 是当前运行时因子缓存，不等同于一次可持久化的 **测试结果**。
