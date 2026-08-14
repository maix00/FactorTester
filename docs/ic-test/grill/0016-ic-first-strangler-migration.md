# Grill 173.17 — 在旧架构外建立结果层并只切换 IC

Status: initial switch boundary rejected; superseded by Grill 173.18

## 用户确定的迁移原则

新结果架构先在现有架构外重新搭建，然后逐个 TestModule 切换。本期只切换 IC 测试：

```text
现有 Job Queue / Worker / RunSpec
  ├─ IC ----------------------> 新 ICTestModule + 通用 Result DAG
  ├─ Backtest ---------------> 保持旧实现
  ├─ Factor Evaluation ------> 保持旧实现
  └─ Factor Type Analysis ---> 保持旧实现
```

不能为了建立通用层而同时改写所有测试，也不能要求旧模块立即实现新接口。

## 新架构放在哪里

先建立与旧实现并列的通用基础层和 IC 领域实现：

```text
tools/testers/results/             # 通用协议、planner、executor
tools/testers/ic_test/results/     # IC kernels、结果类型、artifacts
tools/testers/ic_test/module.py    # ICTestModule
```

旧代码继续存在：

```text
server/modules/single_factor_test/ic.py
tools/factors/tester_calc/single_factor_test/ic.py
```

实现阶段可以调用旧代码中已经正确的底层统计函数，但不能让新 Result DAG 依赖旧的
`_build_ic_response()` JSON 结构；否则只是给旧架构包一层新名称。

## 当前实际调用链

当前提交链路是：

```text
research_jobs._submit_kind("ic")
  -> runner_path:
     server.modules.single_factor_test.process_runners:run_ic
  -> verify_execution_plan("ic", payload)
  -> execute_ic_run_spec(...)
  -> _run_ic_compute_to_sink(...)
  -> _build_ic_response(...)
  -> sink.emit_result(response)
```

原提案把切换边界放在 `process_runners.run_ic`，仍然保留函数式 runner dispatch：

```text
research_jobs._submit_kind("ic")
  -> process_runners.run_ic
  -> verify_execution_plan("ic", payload)
  -> ICTestModule.from_run_spec(payload)
  -> ICTestModule.execute(TestRuntime)
  -> shared Result DAG
  -> requested Artifacts
  -> sink
```

这个边界被拒绝。最终架构不应存在 IC 专属 `run_ic`：

```text
Job execution worker
  -> load one TestModule binding
  -> TestModule.from_run_spec(...)
  -> TestModule.execute(TestRuntime)
```

旁路必须从 worker dispatch 开始建立，详见
`0017-worker-to-test-module-dispatch.md`。

## 迁移期间的复用边界

允许复用：

- RunSpec 冻结和执行计划校验；
- 因子解析、产品选择和数据加载；
- FactorEvaluationContext；
- 已核对统计语义的纯计算函数；
- Job sink、进度、取消和错误通道。

暂不复用：

- `_ICComputeResult` 作为公开结果协议；
- `_build_ic_response()` 的页面 JSON 组织；
- 旧 FactorTester 的结果分发职责；
- 旧页面决定计算哪些统计结果的逻辑。

任何复用都应指向最小纯函数或稳定输入契约，不能让新 ICTestModule 回调旧的完整 IC runner。

## 切换顺序

建议按可独立测试的顺序实施：

1. 建立通用 Result ID、IntermediateResult、Kernel、Artifact 和 DAG executor；
2. 用无 FactorTester 依赖的微型测试验证 DAG；
3. 建立 ICTestModule 和 IC Result IDs；
4. 先接入 IC series 与 coverage kernel；
5. 接入 summary stats kernel；
6. 接入第一组 table/chart Artifacts；
7. 对同一冻结 RunSpec 比较旧路径和新路径的统计结果；
8. 将 IC Job 的执行绑定切到 TestModule worker dispatch；
9. 验证真实异步 Job、取消、错误、结果存储和 UI；
10. 稳定后删除不再被调用的旧 IC 响应组装路径。

这不是运行时同时维护两套永久输出协议。旧路径只用于切换前的测试基线。

## 对以后其他模块的约束

IC 切换完成后，不自动迁移回测或其他模块。每个模块单独进行：

```text
领域结果审计
  -> Result IDs
  -> kernels
  -> Artifacts
  -> 旧新结果对照
  -> 单独切换入口
  -> 删除该模块旧输出路径
```

IC 实现中不得写入“所有 TestModule 都必须具有 IC 矩阵”之类的领域假设。通用层能否被第二个
模块使用，要在未来迁移第二个模块时重新验证，而不是现在提前设计所有可能性。

## 已拒绝的回滚开关

不增加 `GTHT_IC_RESULT_PIPELINE=legacy|result_dag`。当前 branch/worktree 已经提供开发隔离和
回滚边界；再增加运行时开关只会制造第二套状态。
