# Grill 173.15 — Result ID 驱动的中间计算 DAG

Status: architecture accepted; resolver governance rejected and simplified below

## 用户提出的模型

中间计算模块是确定性的计算节点：

```text
kernel_id
requires Result IDs
provides Result IDs
compute(inputs) -> IntermediateResult
```

它可以：

- 只提供一个 Result ID；
- 一次计算提供多个 Result IDs；
- 依赖其他模块已经提供的 Result IDs；
- 由若干更底层 Result IDs 聚合出新的中间结果；
- 让 Artifact 通过 resolver 取得单个 Result；
- 让 Artifact 直接使用或进一步加工整个中间结果。

例如：

```text
IC 序列计算
  provides: single_factor_ic_series

IC 统计矩阵
  requires: single_factor_ic_series
  provides:
    single_factor_ic_mean
    single_factor_ic_std
    single_factor_icir
    single_factor_ic_t_stats
```

因此需要的不是按 Result ID 逐项执行，而是根据 Artifact 需求反向寻找 provider，形成一个
进程内的确定性计算 DAG。

## 三种标识必须分开

### Artifact ID

用户可请求的研究输出，例如汇总表、分布图或序列图。它声明所需 Result IDs，不指定具体
kernel。

### Result ID

稳定的、带类型与 schema 的可消费事实，例如：

```text
single_factor_ic_series
single_factor_ic_mean
single_factor_icir
```

更换或合并 kernel 时，只要统计语义没有变化，Result ID 不应变化。

### Kernel ID

确定性计算实现的标识。它用于执行计划、缓存、审计和性能分析，不是用户接口，也不应被
Artifact 当作稳定统计语义。

## IntermediateResult 的输出契约

每种中间结果声明：

```text
result_type_id
provided_result_ids
每个 Result ID 的 value type/schema
每个 Result ID 的 resolver
```

resolver 只负责从已经得到的中间结果提取、投影或轻量派生一个 Result；它不应重复重型矩阵
计算。

resolver 不建立独立的治理对象，也不进入数据库。它就是中间结果类上固定的代码属性，可以
是 lambda 或普通函数：

```python
class ICStatsMatrixResult:
    result_outputs = {
        "single_factor_ic_mean": ResultOutput(
            value_type="Series[float64]",
            resolve=lambda result: result.values["mean"],
        ),
    }
```

不需要 resolver ID、resolver version、输入输出 hash 或单独的持久化记录。代码提交、
TestModule 类型、冻结 RunSpec 和 kernel receipt 已足够定位当时使用的实现。

运行时只把中间结果对象交给 Artifact 管线，不序列化 resolver 本身。若中间结果必须跨进程
传输，只传数据并在消费进程通过中间结果类型重新获得类属性。

## Artifact 直接消费中间结果

允许 Artifact 直接加工整个中间结果是合理的，例如热力图可能需要完整 IC 统计矩阵，而不是
逐个取 mean、std 和 t-stat。

但 Artifact 不应直接声明依赖某个 `kernel_id`，否则 Artifact 会和具体计算实现耦合。更稳定
的做法是让中间结果整体也拥有一个 Result ID，例如：

```text
single_factor_ic_stats_matrix
```

于是：

```text
summary table
  -> 通过 resolver 使用若干指标 Result IDs

IC heatmap
  -> 直接使用 single_factor_ic_stats_matrix
```

两者仍走同一套 Result 契约，不需要再创造“kernel 直连 Artifact”的第二套依赖机制。

## 规划与执行

组织层按以下顺序工作：

```text
requested Artifact IDs
  -> required/supplemental Result IDs
  -> 为每个 Result ID 选择唯一 provider
  -> 递归加入 provider 所需 Result IDs
  -> 检测缺失 provider、歧义和环
  -> 拓扑排序并去重 kernel
  -> 同一 worker 内每个 kernel 最多执行一次
  -> 生成 Result Store
  -> Artifact 消费 Result 或整体中间结果
```

初版应要求一个 Result ID 在一个 TestModule 版本内只有一个 provider。若以后需要算法变体，
应由 RunSpec 中的统计方法选择先确定 provider，而不是让 resolver 临时猜测。

这个 DAG 是普通确定性数据流，不需要 LangGraph，也不应调用 LLM。

## TestModule 返回值

不宜再假设所有输出必须塞进一个固定字段的巨型 `ICComputationResult`。更合适的是返回带 IC
领域身份的图执行结果：

```text
ICComputationResult
  run identity
  requested Artifact IDs
  executed kernel receipts
  Result Store
  intermediate result refs
  warnings/limitations
```

它是 TestModule 的最终返回值，也是 Artifact 管线的上游中间结果容器；真正的数值仍由
Result ID 定位。

## 函数调用开销

单纯多调用一次 Python 函数或 lambda，通常远小于 pandas/NumPy 矩阵运算、数据加载、复制和
序列化成本。合理粒度下，这个设计不会产生有意义的函数调用瓶颈。

真正可能造成开销的是：

1. 每个标量指标都建立一个重型 kernel；
2. resolver 每次都复制 DataFrame/Series，而不是返回视图或共享只读对象；
3. 多个 Artifact 重复执行相同 resolver 或 kernel；
4. 每个节点都跨进程、写数据库或建立独立 Job；
5. 节点之间反复 JSON/Arrow/Pickle 序列化；
6. planner 每次请求都扫描所有 TestModule 和所有 kernel；
7. 匿名 closure 捕获大型中间对象，造成内存保留。

初版约束：

- 以矩阵运算边界划分多输出 kernel，不按标量 Result ID 拆 kernel；
- 整个 DAG 在一个 Job 的同一 TestModule worker 内执行；
- 节点间只走内存 Result Store，不做数据库读写；
- kernel 按 `kernel_id + input identity + RunSpec identity` 每次计划只执行一次；
- resolver 默认轻量、无副作用；非轻量 resolver 的返回值按 Result ID 在本次运行中 memoize；
- Artifact 共享同一 Result Store；
- 只持久化最终选择的 Result、Artifact、kernel receipt 和必要审计引用；
- Registry 在 worker 启动或模块装载时建立索引，不在每次解析时全量反射扫描。

性能验收应分别测量：

- planner 时间；
- kernel 时间；
- resolver 时间及调用次数；
- DataFrame/Array 复制量；
- 峰值内存；
- 序列化与数据库写入量；
- 两个 Artifact 共享同一 IC 序列和统计 kernel 时是否只计算一次。

## 与现有回测 Flow 的关系

现有 native backtest `FlowDefinition` 已有 `inputs`、`outputs` 和 `compute`，但它服务于：

- PRE_REPLAY / PER_EVENT / POST_REPLAY phase；
- EventKind；
- 人工 order、before、after；
- 回测 FieldRef 和事件时序。

它可以作为设计经验，但不能直接作为 IC Result DAG。IC 需要根据 Artifact 的 Result 需求
反向裁剪节点，并按 provider 关系形成拓扑。若以后 IC、回测和其他测试都需要这套能力，可提取
一个领域无关的小型 computation DAG 基础层；回测事件 Flow 不应反向依赖它。

## 已确认

接受以下架构：

> 由进程内确定性 Result DAG 编排中间计算模块；每个模块声明 required/provided Result IDs，
> 可一次提供一个或多个 Result；Artifact 如需整个中间结果，通过该对象的稳定整体 Result ID
> 消费，不能直接绑定 kernel ID；同一 Job、同一 worker 内去重执行，节点之间不产生数据库、
> IPC 或独立 Job。

resolver 的独立 identity、版本和数据库持久化方案被拒绝。resolver 只是中间结果类型在代码
中固定的属性。

通用化到 IC 以外测试模块的设计继续见 `0015-shared-result-computation-foundation.md`。
