# Grill 173.3 — 测试模块与结果注册

Status: proposed

## 用户提案

各种测试实现为某种测试模块对象的子类；每个模块登记自己可以返回的结果。`FactorTester` 只负责把调用方需要的结果请求分发给对应测试模块，Job 通过 `FactorTester` 执行测试并取得结果。

## 代码审计

当前代码已经分别存在该设计的局部组成部分，但没有统一：

- `FactorTester._TASK_HANDLERS` 已经是函数级任务分发表，`dispatch()` 是薄路由；
- `research_jobs._submit_kind()` 另有一张 Job kind 到 process runner 的硬编码分发表；
- IC、因子评估、因子类型分析和分组回测分别自行创建、读取或绕过 `FactorTester`；
- backtest 的 `output_requests` 已经是结果请求雏形，但只覆盖回测报告；
- settings registry 的 `ResultTabDefinition` 只登记 UI 结果页，不是计算结果契约；
- Worker Sink 已统一实时事件、持久化摘要和 artifact，但不知道各测试可以产生哪些领域结果。

因此当前有三份彼此独立的登记事实：FactorTester task、Job runner 和 UI result tab。

## 修正版

该提案合理，但需要以下边界：

1. 测试模块不是 `FactorTester` 的子类；它们实现一个很小的 `TestModule` 接口，由 `FactorTester` 注册和分发。
2. 每次运行创建本次运行的模块实例，避免跨 Job 共享可变测试状态。
3. 模块登记的是命名的结果能力，而不是 HTTP JSON 字段，例如：
   - `ic.observations`
   - `ic.summary`
   - `ic.coverage`
   - `ic.diagnostics`
4. 每项登记至少声明结果 ID、schema、生成成本、依赖结果和保留方式；Renderer 根据结果 ID 选择输入。
5. JobSpec 在运行前携带结果请求；worker 内的 Job 调用 `FactorTester`，`FactorTester` 将请求交给模块，模块把结果交给 Job Sink。
6. Job 终态后不再访问 `FactorTester`。此时只允许读取已持久化的紧凑摘要和 artifacts，因为 worker-local `FactorTester` 已不存在。
7. 统计事实由测试模块负责产生并登记；外部 Renderer 只消费已登记结果生成表格、图像和报告，不再增加独立“统计派生层”。

## 建议的最小调用形态

```text
JobSpec(kind, requested_result_ids)
  -> worker 创建 FactorTester
  -> FactorTester.dispatch(kind, requested_result_ids)
  -> TestModule.run(context, RunSpec, requested_result_ids)
  -> Module Result(s)
  -> Job Sink: live / summary / artifact
  -> Renderer: table / image / report
```

`FactorTester` 不理解 `ic.summary` 的内部字段，也不负责绘图；它只解析测试类型、验证请求是否已登记并调用正确模块。

## 后续问题拆分

此前把结果注册、请求时点和保留策略放在同一个问题中，范围过大。后续必须按以下顺序逐项 Grill：

1. 当前 Job 与 `FactorTester` 的真实分发关系；
2. `TestModule` 在分发阶段最少登记什么；
3. 结果 ID 与结果对象的关系；
4. 请求时点；
5. 保留与重新渲染。

本文件不再预判第 3–5 项。
