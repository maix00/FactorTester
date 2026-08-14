# Grill 173.24 — FlowBase、FieldRef 与 Result ID 复用审计

Status: superseded by Grill 173.25

> 本文“回测只增加只读 Adapter、运行路径零修改”的结论，已被
> [Grill 173.25](0024-unified-state-result-flow.md) 取代。静态声明审计与现有代码事实仍可
> 作为迁移依据；新的目标是让 IC 与回测完成后的结果推导共用 Result Flow。

## 审计结论

可以抽取共享 Flow 语义，但不应让 ResultFlow 直接继承当前 native `FlowDefinition`，也不应
直接使用 `FlowContext`、`FlowRegistry` 或 `sort_and_validate()`。

推荐的共享 Seam 是：

```text
FlowDeclaration + TypedPort Interface
             ├─ Backtest Flow Adapter
             └─ Result Flow Definition
```

它实现了用户提出的 `FlowBase` 目标，但以组合而不是脆弱的 dataclass 继承表达。

## 当前代码已经有利于抽取

ADR-034 已将：

```text
FlowDefinition：逻辑步骤做什么
FlowBinding：逻辑步骤在哪里运行
```

分开。

因此 `phase`、`event_kind`、`order`、`after`、`before` 已经不在 `FlowDefinition`，而在
`FlowBinding`。用户提出“EventKind 等由子类/领域层拥有”与现有决策一致。

当前 `FlowDefinition` 中仍混有回测专属默认：

- `strategy_scoped`；
- `input_materialization`；
- `event_payload_inputs`。

这些不能进入通用声明。

## FieldRef 与 Result ID

两者扮演相同角色：

```text
Flow 边上的 typed port identity
```

但不建议让二者成为同一个 runtime class 或 type alias。

```python
class TypedPort(Protocol):
    @property
    def qualified_name(self) -> str: ...
```

```text
FieldRef[T] ─┐
             ├─ TypedPort
ResultID[T] ─┘
```

原因不在于字段数量，而在于领域不变量：

| 不变量 | FieldRef | Result ID |
|---|---|---|
| 生命周期 | 一个 phase/event batch 中的槽位 | 一个测试执行中的研究事实 |
| producer | 可以有多个，按 order 覆写 | 默认唯一 provider |
| overwrite | 合法 | 禁止 |
| 无 producer input | 可来自 run state/跨 group | 必须声明为 seed/external input |
| owner | 现有 ExecutableModule 自动填入 | 应有稳定、显式的结果 namespace |
| commit | compute 过程中写 context/state | outputs 验证后原子写 Result Store |

若使用同一个 nominal type，native scheduler 可能误收 Result ID，Result Store 也可能误收瞬时
FieldRef；类型系统不能帮助发现接错 executor 的错误。

这里 `ResultID[T]` 指声明式结果槽位，不是数据库中某次结果实例的主键。

## 三种接口方案

### 方案一：直接引用 native FlowDefinition

拒绝。

调用者需要知道：

- strategy scope；
- input materialization；
- event payload；
- `compute(state, FlowContext) -> None`；
- native owner auto-binding。

ResultFlow 会携带大量无意义的 Interface，降低 Depth，也让通用结果层反向依赖 native backtest。

### 方案二：继承式 FlowBase

技术上可行但不推荐作为最终 Interface：

```python
FlowBase[PortT, StateT, RuntimeT, ReturnT](
    name,
    inputs,
    outputs,
    compute,
)
```

优点：

- `FlowDefinition` 当前前四个构造字段正好匹配；
- 只让 `FlowDefinition` 继承时可以保持其构造方式；
- compute 可通过泛型区分回测与 Result 返回类型。

问题：

- 四个类型参数和 dataclass 字段顺序成为所有维护者都必须理解的 Interface；
- executor 仍不能通过 FlowBase 统一调用 compute；
- 共享 Module 实际只减少四个字段，Deletion test 显示其 Leverage 有限；
- legacy `Flow(name, inputs, outputs, phase, compute, ...)` 不能安全继承，构造顺序会改变；
- 容易继续把 owner、description、领域默认和 validation 塞进父类。

若坚持继承，只能让逻辑 `FlowDefinition` 继承；绝不能迁移 legacy `Flow` convenience class。

### 方案三：组合 + Protocol

推荐。

```python
@dataclass(frozen=True)
class FlowID:
    namespace: str
    name: str

@dataclass(frozen=True)
class FlowDeclaration(Generic[PortT]):
    flow_id: FlowID
    inputs: tuple[PortT, ...]
    outputs: tuple[PortT, ...]
    description: str = ""

class DeclarativeFlow(Protocol[PortT]):
    @property
    def declaration(self) -> FlowDeclaration[PortT]: ...
```

领域定义分别组合 compute：

```python
@dataclass(frozen=True)
class ResultFlowDefinition:
    declaration: FlowDeclaration[ResultID[Any]]
    compute: ResultCompute
```

回测本期不改现有对象，只提供只读 Adapter：

```python
@dataclass(frozen=True)
class BacktestFlowDeclarationAdapter:
    declaration: FlowDeclaration[FieldRef[Any]]
    source: FlowDefinition | FlowBinding | ResolvedFlow
```

这形成真实 Seam：

- `FlowDeclaration` 集中逻辑身份、端口和静态 manifest；
- `DeclarativeFlow` 让静态检查只依赖小 Interface；
- compute、Binding、planner、context、executor 与运行期不变量保持领域 Locality。

## 为什么 compute 不进入共享 declaration

回测：

```text
compute(BacktestRunState, FlowContext) -> None
```

Implementation 会修改 context、domain store、Ledger、EventQueue，并可能反复运行。

Result：

```text
compute(ResultInputs, TestRuntime) -> IntermediateResult
```

Implementation 读取冻结输入，返回 outputs，由 executor 校验后原子提交。

把两者统一成 `Callable[..., Any]` 只是把差异从类型声明赶到运行时报错，形成浅 Module。共享
declaration 不负责调用；两个 executor 是两个 Adapter。

## 不能直接复用的现有基础设施

### FlowRegistry

当前 key 是 `(name, phase, event_kind)`，只能注册 `Flow | FlowBinding`，属于回测 Binding
registry。

### sort_and_validate

它不是需求驱动拓扑排序，而是：

1. 按 `(order, name)` 排序；
2. 验证 reader 前面至少有一个 producer；
3. 允许同一 FieldRef 被后续 producer 覆写；
4. 允许 group 外部输入没有本 group producer。

Result Flow 需要：

- 从 Artifact Result IDs 反向裁剪；
- 唯一 provider；
- 显式 seed；
- cycle detection；
- 真正拓扑排序；
- outputs/schema 全部通过后原子提交。

把两个 planner 做成带大量 policy flags 的“通用 graph”会暴露比各自实现更多的 Interface，
降低 Locality。

### FlowContext 与 runtime audit

当前 FlowContext 包含 EventQueue、Strategy、Ledger、EventDraft 和 batch scope。ResultFlow
不能引用。

可复用“声明 inputs/outputs 并审计未声明访问”的原则，但 Result runtime audit 需要独立
Implementation。等两个 Adapter 都稳定后，再判断是否抽取无领域的 PortAccessAudit。

## owner 与身份

现有 `ExecutableModule.__init_subclass__` 通过 `object.__setattr__` 给直接类属性自动填 owner。
本期保留，不移动，也不让 Result TestModule 继承 ExecutableModule。

Result Flow 推荐显式身份：

```python
FlowID(namespace="single_factor.ic", name="observation")
ResultID(namespace="single_factor.ic", name="series")
```

显式 namespace 避免结果身份随 Python 类名或 auto-binding 改变。

## 最小迁移路径

1. 冻结现有 native Flow manifest 黄金快照：
   - definition/qualified/binding names；
   - inputs/outputs；
   - phase/event/order；
   - owner；
   - 当前 Registry 全量声明。
2. 在中性目录新增 stdlib-only `flow_core`：
   - `TypedPort`；
   - `FlowID`；
   - `FlowDeclaration`；
   - `DeclarativeFlow`。
3. 新增独立 ResultFlow definition/context/planner/executor。
4. IC 使用 ResultFlow。
5. 新增只读 BacktestFlowDeclarationAdapter，仅用于 manifest 与静态合同对照，不替换：
   - FlowDefinition/Flow；
   - FlowRegistry；
   - scheduler；
   - FlowContext；
   - 任何回测声明。
6. IC 稳定且第二个 TestModule 接入后，再审计：
   - 是否让 native FlowDefinition 原生组合 FlowDeclaration；
   - 是否抽 owner helper；
   - 是否抽无领域 PortAccessAudit。

当前 checkout 实际 Registry 可解析 72 个 Flow 声明且 owner 缺失为 0。实施前应将此全量
manifest 与既有验收集合共同作为回归基线。

## 测试要求

- 现有 Flow/FlowBinding 构造签名不变；
- native manifest 黄金快照不变；
- native sort/overwrite/external-input 测试不变；
- ResultFlow 重复 provider、缺失 seed、cycle、自环必须失败；
- ResultFlow compute 少返回、错类型或多返回 output 时原子提交失败；
- FieldRef 不能注册进 ResultGraph；
- ResultID 不能注册进 native FlowRegistry；
- Backtest read-only Adapter 不修改 owner 或 definition；
- IC 多输出 ResultFlow 只执行一次。

## 待确认

是否接受：

> 把用户所称 `FlowBase` 实现为组合式 `FlowDeclaration + TypedPort Interface`，而不是父类；
> `FieldRef[T]` 与 `ResultID[T]` 实现同一 typed-port Interface 但保持名义类型隔离；两个
> executor、planner、context 与 producer policy 不共享；本期 backtest 只增加只读 Adapter，
> 运行路径零修改。
