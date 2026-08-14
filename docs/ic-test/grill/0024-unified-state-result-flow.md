# Grill 173.25 — 可变状态 Flow 与不可变结果 Flow 的统一设计

Status: partially accepted; top-level executor design superseded by Grill 173.26

> `FlowRef / StateRef / ResultRef`、Freeze 边界和回测结果计算接入 Result Flow 已获接受。
> 本文保留两个并列顶层 executor 的方案已被
> [Grill 173.26](0025-composite-lifecycle-flow.md) 取代：顶层改为一个统一
> `FlowPlanExecutor`，回测生命周期作为复合 Flow 参与同一计划。

## 本轮修正

前一轮把共享层限制成“声明与只读 Adapter”，低估了回测结束后的结果计算：

- 收益率序列；
- Sharpe、最大回撤等风险与绩效指标；
- portfolio、target trace 等最终投影；
- 净值曲线、统计表格和其他 Artifact。

这些并不是回测事件循环本身，而是对已完成回测事实的确定性推导。它们与 IC 统计具有相同
语义：从已发布的输入结果，按 Artifact 需求计算并发布新的结果。因此，IC 与回测应在
Result Flow 层深度融合。

但“深度融合”不等于用一个万能 executor 同时解释事件循环、账本副作用、可变状态、按需
DAG 和 write-once 结果。共享 Module 应具有足够 Depth，同时保留两种执行语义的 Locality。

## 当前 POST_REPLAY 的实际分类

现有回测结束路径并不是一种同质工作：

| 当前步骤 | 真实语义 | 目标归属 |
|---|---|---|
| `flush_equity_post_replay` | 把 buffer 写入可变 ResultStore 的终结动作 | Lifecycle Flow |
| `compute_risk_metrics` | 从净值事实确定性推导指标，但当前仍隐式读写 mutable state | Result Flow |
| `StrategyRuntime.on_stop` | 生命周期回调，仍允许取消 timer 和修改私有状态 | Lifecycle Flow |
| scheduler 返回后的 portfolio/target trace 拼装 | 从最终状态生成结果投影 | Result Flow |

因此不能把整个 `POST_REPLAY` phase 直接改名为 Result Flow。正确 Seam 位于：

```text
可变生命周期终结
       ↓
Freeze / Publish BacktestResult
       ↓
不可变结果推导
```

## 统一端口模型

用户提出“把 inputs/outputs 区分成可修改值与不可修改值，并继承同一个 base”的方向合理。
这里的“不可修改”首先指发布槽位 write-once，而不是默认深拷贝每个 pandas 对象。

```python
@dataclass(frozen=True)
class FlowRef(Generic[T]):
    key: RefKey
    schema: ValueSchema[T]


@dataclass(frozen=True)
class StateRef(FlowRef[T]):
    """运行期可重复读取、替换或更新的状态槽位。"""


@dataclass(frozen=True)
class ResultRef(FlowRef[T]):
    """一次 Job 中只能由唯一 provider 原子发布一次的结果事实。"""
```

命名映射：

```text
现有 FieldRef  ──Legacy Adapter──> StateRef
Result ID                         ──> ResultRef
```

两者共享端口身份、schema 与 manifest 能力，但保留不同不变量：

| 不变量 | StateRef | ResultRef |
|---|---|---|
| 更新 | 允许 | 禁止二次发布 |
| producer | 可按生命周期顺序有多个 | 唯一 provider |
| 调度 | phase/event/order | Artifact demand + DAG |
| 生命周期 | batch、phase 或一次 run | 一次 Job 的已发布事实 |
| 提交 | 可产生副作用 | 所有 outputs 校验后原子发布 |

`ResultRef` 的 write-once 不能靠 Python `frozen=True` 保护 DataFrame 内容。执行器保护槽位和
所有权转移；NumPy 可无复制设为只读，pandas 默认按 borrowed-read-only 契约传递，审计模式
可做 fingerprint。不能为了“物理不可变”在每个 Flow 深拷贝大曲线。

## 共享 Flow 定义

`phase` 不属于 Flow 的逻辑身份。用户所说的 optional phase，应表达成“可选 Binding”，而
不是一个含义不清的 `phase: Phase | None` 字段：

```python
@dataclass(frozen=True)
class FlowContract:
    flow_id: FlowID
    inputs: tuple[FlowRef[Any], ...]
    outputs: tuple[FlowRef[Any], ...]
    description: str = ""


@dataclass(frozen=True)
class FlowDefinition(Generic[OperationT]):
    contract: FlowContract
    operation: OperationT
```

执行位置由 Binding 指定：

```python
LifecycleBinding(
    phase=Phase.POST_REPLAY,
    event_kind=None,
    order=...,
    after=(...),
    before=(...),
)

DemandBinding()
```

- 有 `LifecycleBinding`：由回测生命周期触发，可使用 `StateRef`。
- 有 `DemandBinding`：由 Artifact 对 `ResultRef` 的需求触发，只运行所需 DAG。
- 不允许用 `None` 同时暗示“没有调度”“运行一次”“按需运行”三种不同含义。

## 一个 Flow Module，两个执行 Adapter

```text
Flow Module
├── FlowContract / FlowRef / manifest / receipt
├── Lifecycle Adapter
│   ├── phase / event / order
│   ├── mutable StateRef
│   └── Ledger、EventQueue 与策略副作用
└── Result Adapter
    ├── Artifact demand 反向裁剪
    ├── unique provider / seed / cycle validation
    ├── write-once ResultRef
    └── atomic output publish
```

共享一个入口是合理的：

```python
class FlowEngine:
    lifecycle: LifecycleExecutor
    results: ResultExecutor
```

但两个 executor 不应合成带大量 policy flags 的万能 executor。否则每次调用都要判断
phase、event kind、mutable/immutable、repeat/write-once 和副作用，Interface 反而变浅。

## 唯一允许的可变到不可变桥

回测必须有一个显式 Freeze Flow：

```python
FreezeBacktestResult(
    inputs=(BACKTEST_RUN_STATE,),   # StateRef
    outputs=(BACKTEST_RESULT,),     # ResultRef
    binding=LifecycleBinding(phase=POST_REPLAY),
)
```

它是受限的 mixed bridge：

1. 允许读取 `StateRef`，只允许输出 `ResultRef`；
2. 只能绑定一次性生命周期位置，禁止在 `PER_EVENT` 重复发布；
3. 必须先完成所有会改变可报告状态的 finalizer；
4. outputs 全部校验成功后一次性发布；
5. 一个 Flow 不得同时写 `StateRef` 和 `ResultRef`，避免部分提交；
6. Freeze 形成 barrier，随后才能并行或缓存 Result Flow；
7. Result Flow 禁止直接读取 `StateRef`，缺少 Freeze 必须编译失败。

当前 `on_stop` 仍可能修改策略私有状态，因此更安全的顺序是：

```text
flush mutable equity
→ on_stop lifecycle
→ freeze BacktestResult
→ result flows
```

如果日后把 `on_stop` 收窄成纯通知/资源清理，才能审计是否放到 Freeze 之后。

## IC 与回测的统一结果路径

### IC

```text
冻结的因子与收益输入
→ ICObservationFlow
→ IC summary / rolling / ACF Result Flows
→ table / chart / report Artifacts
```

### 回测

```text
Lifecycle Flows
→ mutable BacktestRunState
→ FreezeBacktestResult
→ return / drawdown / risk Result Flows
→ table / equity-curve / report Artifacts
```

例如：

```python
PerformanceStatsFlow(
    inputs=(BACKTEST_RESULT,),
    outputs=(RETURN_SERIES, DRAWDOWN, SHARPE),
    binding=DemandBinding(),
)
```

Artifact 仍是用户可请求对象；Artifact 声明必需和附加的 `ResultRef`。Planner 从这些 refs
反向寻找 provider。回测的事件副作用不能因为用户没请求某个 Artifact 就任意裁剪；只有
Freeze 之后的 Result DAG 是 demand-driven。

## Intermediate Result 与 resolver

此前关于 IC 的决定保持不变：

- 一个 kernel/operation 可以一次矩阵运算发布多个 `ResultRef`；
- intermediate result 可以直接被下游 operation 或 Artifact 使用；
- resolver 是中间计算对象固定在代码中的属性；
- resolver 不需要单独版本对象或数据库记录；
- planner 按 declared inputs/outputs 合并共享计算，不能逐个 Result ID 重复调用同一函数。

该机制现在同时适用于回测指标。例如一次收益路径扫描可以同时给出收益序列、回撤路径和
分段统计所需的 intermediate result，而不为每个指标重扫净值。

## 当前命名冲突

现有 native `ResultStore` 是可变的逐策略 history/final 存储，不等于新的 write-once
Result Store。迁移时必须显式改名或包裹，不能让两个对象共享模糊名称：

```text
NativeRunResultStore      # 现有 mutable store
PublishedResultStore      # 新的 ResultRef write-once store
```

## 迁移顺序

1. 为当前 POST_REPLAY 顺序和输出建立 characterization/golden tests。
2. 在现有架构外新增 Flow Core、Result Planner/Executor 和 PublishedResultStore。
3. IC 首先完整接入 Result Flow；其他测试路径不切换。
4. 新增唯一 `FreezeBacktestResult` Adapter，不改事件 scheduler。
5. risk metrics 新旧双跑比对，通过后才切换生产输出。
6. 将 scheduler 返回后的 portfolio/target trace 投影迁入 Result Flow。
7. 再逐项审计回测的其他结果计算；生命周期副作用仍留在 Lifecycle Adapter。
8. 全部 parity 后，才考虑让既有 native Flow 原生采用共享 FlowContract；不做一次性继承迁移。

这满足“先在现有架构外重新搭、一个测试模块一个测试模块切换”的决定，同时为回测结果计算
留下明确的深度融合路径。

## 验收

- 当前 native Flow manifest、顺序与 event 行为保持不变；
- IC Result DAG 的重复 provider、缺失 seed、cycle、自环必须失败；
- Lifecycle Flow 不能被 Artifact demand 非法裁剪；
- Demand Result Flow 不能读取 `StateRef`；
- mixed bridge 不能写 mutable output，不能在重复 phase 发布；
- Freeze 前后的净值、position、notional、margin、execution trace 与配置身份一致；
- equity live-compute 开关下的冻结结果等价；
- 旧新 risk metrics、portfolio 和 target trace 做 golden parity；
- 一个多输出 operation 对同一 Job 只执行一次；
- Artifact 未请求的昂贵结果不得计算；
- 发布失败时 PublishedResultStore 不出现部分 outputs；
- 大净值曲线不因每个 Result Flow 深拷贝或 JSON 化而产生明显内存、延迟回退。

## 待确认

是否接受：

> `FlowRef[T]` 作为共同端口基类，`StateRef[T]` 表达可变运行状态，`ResultRef[T]` 表达
> write-once 结果事实；phase 通过可选的 `LifecycleBinding` 表达，无 phase 的按需计算使用
> `DemandBinding`；IC 与回测 Freeze 之后的指标、投影和 Artifact 共用 Result Flow，而回测
> 事件循环和可变终结仍由 Lifecycle Adapter 执行；两者由同一 Flow Module/Engine 管理，但
> 不强行合并成一个 executor。
