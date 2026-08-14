# Grill 173.4 — 当前 Job 与测试分发

Status: audited; registration proposal open

## Job 公共入口

当前一次异步研究运行的公共入口为：

```text
POST /api/runs
  -> 为 analyses 中每个 kind 建一个 JobRecord
  -> _submit_kind() 按硬编码字典写入 runner_path
  -> Job daemon 把 runner_path 和 payload 送入 worker
  -> worker 动态 import module:function
  -> process runner 执行测试
  -> Worker Sink 接收 result/artifact/progress
```

`_submit_kind()` 当前硬编码四种 Job：

| Job kind | process runner |
|---|---|
| `backtest` | `run_group` |
| `ic` | `run_ic` |
| `factor_evaluation` | `run_factor_evaluation` |
| `factor_type_analysis` | `run_factor_type_analysis` |

Job 只知道 runner path，不知道 `TestModule`，也没有向 `FactorTester` 询问测试能力。

## 四种测试的真实路径

### Backtest / Group

```text
run_group
  -> verify_execution_plan
  -> execute_group_run_spec
  -> prepare_group_run_spec
  -> 建 BacktestRunState
  -> FactorTester(products=[]).dispatch("backtest")
  -> native/external backtest engine
  -> serialize_event_execution
  -> emit_group_run_outputs
  -> sink.emit_result + artifacts
```

这是唯一通过 `FactorTester.dispatch()` 运行完整测试的路径。此处 `FactorTester` 没有承载产品和回测状态；真实运行状态在 `BacktestRunState`。

### IC

```text
run_ic
  -> verify_execution_plan
  -> execute_ic_run_spec
  -> create_isolated_factor_tester_for_run
  -> _prepare_ic_compute
  -> _compute_ic_groups
  -> _build_ic_response
  -> sink.emit_result
```

IC 使用 `FactorTester` 的产品、时间、因子求值缓存和 `FactorRunResult`，但不调用 `dispatch("ic")`。多配置结果先进入 `_ICComputeResult`，最后由 server 模块手工组装响应字典。

### Factor Evaluation

```text
run_factor_evaluation
  -> FactorEvaluation.from_run_spec
  -> FactorEvaluation.run
  -> create_isolated_factor_tester_for_run
  -> tester.calc_factor
  -> tester.results.get(factor)
  -> 手工组装 result dict
  -> sink.emit_result
```

`FactorEvaluation` 已接近测试模块对象，但尚未注册到 `FactorTester`。

### Factor Type Analysis

```text
run_factor_type_analysis
  -> FactorTypeAnalysisRun.from_run_spec
  -> FactorTypeAnalysisRun.run
  -> create_isolated_factor_tester_for_run
  -> 计算目标与参照因子
  -> FactorTypeAnalyzer.analyze
  -> FactorTypeAnalysisResult
  -> server facade 手工投影 result dict
  -> sink.emit_result
```

这里已经有专门结果对象，但执行入口、结果登记和 Job 分发仍彼此分离。

## 当前存在的四类“注册”

1. `FactorTester._TASK_HANDLERS`：低层 factor task 与 `backtest` handler；
2. `_submit_kind.process_runners`：Job kind 到 import path；
3. settings registry：设置模块与 UI `ResultTabDefinition`；
4. Job `output_requests`：目前只定义回测报告输出。

这些登记没有共同权威来源，新增测试或结果必须在多处同步修改。

## 本步的最小 TestModule 登记提案

在“Job 找到并执行测试”这一步，`TestModule` 暂时只需要登记：

1. `kind`：稳定的测试类型 ID，例如 `ic`；
2. `run_spec_contract`：该测试接受的输入 contract 和验证入口；
3. `factory`：如何从冻结 RunSpec 创建本次运行模块实例；
4. `execute`：如何在给定 `FactorTester`/运行上下文和 sink 下执行；
5. `result_ids`：该模块声称能够产生的命名结果 ID，仅用于请求合法性检查。

此步不登记：

- UI tab 或布局；
- Renderer；
- 数据库存储策略；
- 结果字段明细；
- 默认保留策略。

这些内容是否以及如何登记必须后续逐项决定。

类本身如何进入 Registry 已拆分到
`0004-test-module-class-registration.md`；该文件优先决定显式启动注册与失败规则，本文件不再
预设 metaclass 或自动注册。

补充边界：完整 Registry 只属于 Job 控制面。worker 收到的是已经解析并冻结的单项
`TestModuleExecutionBinding`，只加载当前 Job 的测试类，不重新登记全部测试。
