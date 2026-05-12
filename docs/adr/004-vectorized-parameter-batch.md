# ADR-004：参数空间批量计算 — 向量化 Evaluate

- **日期**：2026-05-12
- **状态**：提议中
- **决策者**：FactorTester 团队

---

## 背景

FactorTester 的因子计算链路是：`FactorFamily -> resolve params -> Factor -> evaluate -> FactorTester.test_by_group`。每个参数配置产生一个独立的 Factor 对象，各自 evaluate 返回 `(products x time)` DataFrame，串行执行回测。计算 M 组参数需要 O(M) 时间和 O(M) 内存，不共享子表达式缓存。

未来需要支持参数空间搜索（网格搜索、贝叶斯优化、ML 模型驱动优化），希望批量计算 M 组参数配置，共享子表达式，减少总计算量。

## 决策

**新增 `FactorFamily.evaluate_batch(products, param_matrix)` 方法，在表达式层面支持向量化参数计算。**

### 核心设计

1. **不 resolve，直接 evaluate**：`ParamRef` 在 batch 模式下替换为 `ConstExpr(np.array([...]))`，而非 `ConstExpr(单个值)`。resolve 是纯符号替换（零成本），不需要"向量化 resolve"；关键是让 evaluate 支持数组值。

2. **ConstExpr 支持数组值**：`ConstExpr._evaluate()` 检测 value 是否为 `np.ndarray`。若是，返回 shape 为 `(M, P)` 的 DataFrame（M 参数维度 x P 品种），时间维度通过 index 自然携带。非数组值不变（退化为 M=1）。

3. **算子自动广播**：
   - `RollingOp._evaluate()`：如果 window 是数组，对每组 window 值分别计算滚动窗口，结果 concat 为多参数维度。
   - `ShiftOp._evaluate()`：同上，对每组 shift 步长分别计算，结果 concat。
   - `CrossSectionalOp._evaluate()`：天然兼容 — 横截面运算逐时间点，多列即多参数。
   - `CompositeExpr._evaluate()`：如果 operands 中有带参数维度的 DataFrame，广播到所有 operands。

4. **FactorFamily 新增 API**：
   - `parameter_space(defaults, ranges)` — 根据 `ordered_param_deps` 定义搜索空间（含 $F, $Rev）
   - `evaluate_batch(products, param_matrix)` — 批量计算，返回带参数维度的因子值

5. **FactorTester 新增 API**：
   - `test_by_group_batch()` — 批量回测 M 组参数配置，返回汇总结果

### 数据形状约定

- 当前：`evaluate()` 返回 `pd.DataFrame(products x time)`，列是产品，行是时间
- Batch：`evaluate_batch()` 返回 `pd.DataFrame`，MultiIndex columns：`(param_index, product)`，行是时间。或多维 `xarray.DataArray`

## 后果

### 正面

- 共享子表达式缓存机会大增（M 组参数共享相同的中间计算）
- 向量化运算可利用 numpy/pandas 的 SIMD 优化
- 上层 ML 框架可直接消费 batch 结果
- 不破坏现有 `evaluate()` 接口

### 负面

- `ConstExpr._evaluate()` 需要分支处理标量/数组
- `RollingOp` / `ShiftOp` 的 `_resolve_windows` 逻辑在数组模式下更复杂（多品种 x 多参数 = 两维分组）
- 内存占用可能从 O(P x T) 增加到 O(M x P x T)，需要内存管理策略

### 替代方案

- **方案 B：不改表达式引擎，仅在调度层批量** — M 组参数仍各自创建 Factor，但用进程池并行 + 共享 FactorData 缓存。实现简单但内存不共享、不解决根本效率问题。
- **方案 C：引入外部计算框架（Ray/Dask）** — 太重，不适合当前项目规模。
