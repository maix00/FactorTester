# Grill 173.5 — TestModule 类注册机制

Status: proposed

## 本轮问题

`TestModule` 是测试基类，不同测试是它的子类。需要确定
`TestModuleRegistry` 是否应当作为 `TestModule` 的 metaclass，以及测试类究竟在何时、
由谁、以什么失败规则登记。

## 结论建议

`TestModuleRegistry` **不应当是 metaclass**。

- `TestModule` 是抽象基类，规定“一个测试模块是什么”；
- `ICTestModule`、`BacktestTestModule` 等是它的具体子类；
- `TestModuleRegistry` 是普通运行时目录对象，规定“控制面允许提交哪些测试类”；
- 注册表保存测试**类**，不保存跨 Job 复用的测试实例；
- 每个 Job 取得类后再创建自己的模块实例。

如果 `TestModule` 使用 `abc.ABC`，它本身已有 `ABCMeta`。没有必要为了注册再引入一个
自定义 metaclass，也不应当让“类定义成功”自动等于“测试已获准在生产运行”。

## 仓库现有先例

当前回测模块已经把“类初始化”和“类注册”分开：

1. `ExecutableModule.__init_subclass__` 只为 `FieldRef`、`Flow` 等类内声明补全 owner；
2. `_ALL_MODULE_CLASSES` 显式列出允许使用的模块类；
3. `ModuleRegistry.__init__` 校验空 key 和重复 key，再构建 `_by_key`；
4. 调用方通过 registry 查类或创建实例。

因此，文件头所说的 “self-registers” 并不是 metaclass 自动登记；真实代码仍以显式类清单
作为权威来源。`TestModule` 应沿用这种可审计语义，并把命名进一步改准确。

## 为什么不使用自动注册

以下三种写法都依赖 import 副作用：

```python
class TestModuleMeta(type):
    def __new__(...):
        GLOBAL_REGISTRY.register(new_class)
```

```python
class TestModule:
    def __init_subclass__(cls, **kwargs):
        GLOBAL_REGISTRY.register(cls)
```

```python
@register_test_module
class ICTestModule(TestModule):
    ...
```

它们的问题相同：

- 可用测试集合取决于模块是否以及按什么顺序被 import；
- server、worker、CLI 或测试进程可能得到不同的集合；
- reload、测试隔离和重复 import 容易产生重复登记或静默覆盖；
- 仅仅 import 一个第三方包就可能改变生产执行能力；
- 无法清楚区分“代码里定义了这个类”和“本次部署批准启用这个测试”。

`__init_subclass__` 可以继续用于**类自身的声明校验或元数据补全**，但不能修改全局
Registry。

## 建议的类与 Registry 关系

```python
from abc import ABC
from typing import ClassVar


class TestModule(ABC):
    kind: ClassVar[str]


class ICTestModule(TestModule):
    kind = "ic"


class BacktestTestModule(TestModule):
    kind = "backtest"


class TestModuleRegistry:
    def __init__(self) -> None:
        self._by_kind: dict[str, type[TestModule]] = {}
        self._frozen = False

    def register(self, module_cls: type[TestModule]) -> None:
        ...

    def require(self, kind: str) -> type[TestModule]:
        ...

    def freeze(self) -> None:
        ...
```

本轮只规定 Registry 登记类身份。`RunSpec` 工厂、执行方法和结果能力的具体接口留给后续
逐项 Grill，避免一次把多个职责塞进注册协议。

## 控制面的显式启动注册

内置测试由一个权威 bootstrap 文件显式列出：

```python
BUILTIN_TEST_MODULES: tuple[type[TestModule], ...] = (
    BacktestTestModule,
    ICTestModule,
    FactorEvaluationTestModule,
    FactorTypeAnalysisTestModule,
)


def build_builtin_test_module_registry() -> TestModuleRegistry:
    registry = TestModuleRegistry()
    for module_cls in BUILTIN_TEST_MODULES:
        registry.register(module_cls)
    registry.freeze()
    return registry
```

推荐目录边界：

```text
tools/testers/test_modules/
  base.py          # TestModule
  registry.py      # TestModuleRegistry
  builtin.py       # 明确启用的内置测试类清单
```

具体测试实现暂时保留在各自现有领域目录，通过轻量 adapter 进入清单；是否搬迁实现文件应在
接口稳定后另行决定，不能为了注册机制先做大规模目录迁移。

## 当前 worker 的真实生命周期

当前代码使用 `LongLivedWorkerPool`：

```text
服务启动
  -> spawn 固定数量的 worker
  -> worker 初始化一次
  -> 循环从 task_queue 取得 Job
  -> 按该 Job 的 runner_path 动态 import
  -> 执行
  -> worker 保持存活并等待下一项 Job
```

所以严格来说，不是“一个 Job 启动一个新测试进程”。但是无论 worker 是一次性还是长期
复用，单个 Job 的执行路径都只需要当前测试模块，不能因此 bootstrap 全部测试模块。

## 控制面 Registry 与单 Job 执行绑定

完整 Registry 只在控制面建立：

```text
Job 提交
  -> TestModuleRegistry.require(job.kind)
  -> 解析出唯一测试类
  -> 冻结 TestModuleExecutionBinding
  -> binding 随 JobSpec 持久化并送入 worker
```

`TestModuleExecutionBinding` 是单项运行绑定，不是第二个 Registry。例如：

```python
TestModuleExecutionBinding(
    kind="ic",
    implementation_ref="...:ICTestModule",
)
```

具体还需冻结哪些 contract 或 version 字段，留到 RunSpec 接口一轮决定。

worker 的执行路径是：

```text
收到一个 Job
  -> 读取该 Job 已冻结的 TestModuleExecutionBinding
  -> 只 import implementation_ref 指向的模块
  -> 验证该类是 TestModule 子类且 class.kind == binding.kind
  -> 为该 Job 创建实例
  -> 执行
```

worker 不建立全量 `TestModuleRegistry`，也不扫描全部子类。长期 worker 即使因为先前 Job
已经在 Python import cache 中保留其他模块，也不能把这些偶然已加载类视作可用 Registry；
当前 Job 的唯一实现身份仍来自它自己的冻结 binding。

CLI 默认也不需要 import 全部测试实现。连接服务器时，它读取控制面发布的紧凑测试目录；
只有明确执行本地离线测试时，才建立相应的本地 Registry。

## 注册生命周期

```text
控制面进程启动
  -> import builtin.py 明确引用的测试类
  -> 新建空 TestModuleRegistry
  -> 逐类 register
  -> 完整校验
  -> freeze
  -> Job 按 kind require 测试类
  -> 生成该 Job 的单项执行 binding
  -> worker 只加载 binding 指定的测试类
  -> 为该 Job 新建模块实例
```

运行中不允许随意覆盖或删除登记。日后支持外部插件时，也应在一个明确的 bootstrap 阶段
加载获准 provider，再统一校验和 freeze；不能让 Agent 通过临时 import 自动获得执行权限。

## `register()` 的确定性失败规则

登记时至少检查：

1. 参数必须是类；
2. 必须是 `TestModule` 的子类；
3. 不能登记仍含抽象方法的类；
4. `kind` 必须是稳定、非空、规范化的字符串；
5. 同一 `kind` 只能登记一次；
6. 重复 `kind` 必须立即失败，不能 last-write-wins；
7. Registry freeze 后再登记必须失败。

查询未知 `kind` 也必须返回明确的 `UnknownTestModule` 类错误，而不是退回旧硬编码 runner。

## 与 FactorTester 和 Job 的边界

本轮只确定：

```text
Job kind
  -> 控制面的 TestModuleRegistry
  -> require(kind)
  -> 冻结单 Job TestModuleExecutionBinding
  -> worker 只加载该 TestModule 子类
  -> FactorTester 执行当前模块
```

它不意味着 Registry 自己执行测试，也不意味着 Registry 是 FactorTester 的父类。
worker-local `FactorTester` 不需要持有完整 Registry；它只需要接收当前 Job 已绑定的模块。
Job 如何通过统一 runner 调用 `FactorTester`、模块如何从 RunSpec 创建实例，是下一轮需要
单独决定的执行问题。

## 验收要点

- import 一个未列入 `BUILTIN_TEST_MODULES` 的子类不会改变 Registry；
- 控制面完整 Registry 正确登记四种内置测试；
- worker 执行 IC Job 时不会 import 或 register 回测、因子评估和因子类型分析模块；
- worker 拒绝 binding kind 与实际测试类 kind 不一致的任务；
- 空 kind、非子类、抽象类、重复 kind、freeze 后注册均失败；
- Registry 返回类，每个 Job 创建不同实例；
- 新增测试只需要增加实现和权威 bootstrap 登记，不再增加另一张 Job runner 映射表；
- 现有测试语义和结果内容在仅替换分发注册机制时保持不变。

## 本轮待确认

是否接受“`TestModule` 使用普通抽象基类；只有 Job 控制面显式建立并 freeze 完整
`TestModuleRegistry`；Job 冻结单项执行 binding，worker 只加载该 Job 的测试类，不建立
完整 Registry；禁止 metaclass、decorator 或 `__init_subclass__` 自动注册”的方案？
