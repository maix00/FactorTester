# 架构深化 TODO

> 来源：`improve-codebase-architecture` skill 扫描结果（2026-05-12）
> 每个候选标注了涉及的模块、问题和收益

---

## 1. 移除 `Factor.__getattr__` 隐式代理

- **文件**：`tools/factors/Factors.py`
- **问题**：`Factor` 通过 `__getattr__` 把未命中属性转发到 `self._expr`，导致 Factor 接口暴露出整个 FactorExpr DSL（~50 个方法），类型检查器无法区分"表达式模板"和"已解析因子"
- **方案**：移除 `__getattr__`，调用方显式使用 `factor.expr.xxx`
- **收益**：Factor 接口从 ~50 个方法降到 ~8 个；类型检查可行；新开发者不会困惑

## 2. `FactorTester` 的 8 个 factor-keyed 字典 → `FactorRunResult`

- **文件**：`tools/factors/FactorTester.py`
- **问题**：`calc_factor()` 把结果写入 8 个 `tester.*` 字典而非返回；同一 factor 的状态分散；隐式依赖 `_active_tester` ContextVar
- **方案**：`calc_factor()` 返回 `FactorRunResult` dataclass，调用方管理生命周期
- **收益**：去掉 8 个字典；`Factor.evaluate()` 不再需要 `_active_tester`；每个 factor 的结果可独立测试

## 3. `evaluate()` 签名统一为 `EvaluateContext`

- **文件**：`tools/factors/FactorExpr.py`
- **问题**：`ColumnRef._evaluate(products, freq, source, cache, preloaded)` vs `ConstExpr._evaluate(**kwargs)` vs `RollingOp._evaluate(...)` — 5 种签名变体，类型检查器无法验证
- **方案**：定义 `EvaluateContext(products, freq, source, cache, preloaded)` NamedTuple，所有节点接受 `ctx: EvaluateContext`
- **收益**：一改全改；新算子只关注自己逻辑；类型检查器能捕获调用错误

## 4. `_active_tester` ContextVar → 显式参数

- **文件**：`tools/factors/FactorTester.py`、`tools/factors/Factors.py`、`tools/data/DataMeta.py`
- **问题**：3 个模块隐式消费 `_active_tester.get()`；`DataMeta._filter_data_by_start_calc_point()` 无 tester 上下文时静默用默认值
- **方案**：将 `start_calc_point` 作为显式参数传入 `DataMeta`，或通过 `EvaluateContext` 传递
- **收益**：`DataMeta` 可脱离 Flask/tester 测试；调用链路完全透明

## 5. 统一重复的图遍历逻辑

- **文件**：`tools/factors/FactorExpr.py` 和 `tools/factors/Factors.py`
- **问题**：`_iter_intermediate_nodes()` 和 `_collect_intermediates_from_cache()` 各自实现了相同的"遍历树 → 找 `_is_intermediate` 节点"逻辑
- **方案**：抽 `iter_intermediate_nodes(expr) -> Iterator[FactorExpr]` 到 FactorExpr 基类
- **收益**：一处改 bug 两处受益；新加中间因子特性不需记住改两个文件

## 6. `$` 前缀规范化 — 内部统一用 `$F`

- **文件**：`tools/factors/FactorFamily.py`
- **问题**：因子参数有时传 `F`，有时传 `$F`；`_normalize_param_kwargs()` 做双向转换
- **方案**：在 HTTP 接入层统一转换为 `$F` 形式，内部代码只认 `$F`（不保留无 `$` 前缀的兼容）
- **收益**：去掉 ~30 行双向转换逻辑；一个参数名只有一个规范形式
