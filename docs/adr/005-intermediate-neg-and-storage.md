# ADR 005: intermediate 缓存与 $Rev 取反的数据流约定

## 时间
2026-05-14

## 状态
已接受

## 背景

Factor 有三层表达式：
- `_source_expr = source_expr`（无 $Rev, 无 SignalAlign）
- `_func_expr = neg(source_expr)`（可能有 $Rev, 无 SignalAlign）
- `_expr = neg(SignalAlign(source_expr, ...))`（可能有 $Rev + SignalAlign）

`$Rev` 因子的 `_func_expr` 是 `neg(source_expr)`，无 `$Rev` 因子的 `_func_expr` 是 `source_expr`。

`as_intermediate(name)` 标记表达式节点为中间因子，evaluate 后数据存入 `Factor._intermediate_factor_data[structural_key]`，可通过 `get_intermediate(name)` 查询。

**历史问题**：`as_intermediate()` 曾有一段穿透 neg 的逻辑（commit `a3678ec` 引入）：
```python
if isinstance(self, OperandExpr) and self.op == 'neg':
    self._is_intermediate = False
    return CompositeExpr('neg', self.operands[0].as_intermediate(name, factor))
```
这导致 `neg(source_expr).as_intermediate('FE')` 把 intermediate 标记在 `source_expr` 上（而非 `neg(source_expr)`），$Rev 与无 $Rev 因子共享同一个 structural_key → `get_intermediate("FE")` 返回相同数据 → 分组测试中两者结果相同（#24）。

## 决策

### 1. `as_intermediate` 不再穿透 neg

`as_intermediate` 直接标记当前节点，不穿透任何层。调用方自行决定在何处标记：
- 需要存无 neg 的数据 → 在 `source_expr` 上调用 `.as_intermediate()`
- 需要存带 neg 的数据 → 在 `neg(source_expr)`（`_func_expr`）上调用 `.as_intermediate()`

### 2. 数据流约定（两级写入路径）

| 调用方 | as_intermediate 标记在 | 写入目标 | 是否 copy |
|--------|----------------------|---------|----------|
| 直接 evaluate 因子（`Factors.py`） | `source_expr`（无 neg） | `FactorRunResult.source_table` | 否（$Rev/无 $Rev 公用一份 pd.DataFrame） |
| IC 因子 evaluate（`run_ic_for_factor`） | `_func_expr`（可能有 neg） | `FactorRunResult.func_table` | 否 |

### 3. `FactorRunResult` 中的 `_func_table`/`_source_table` 双向互查

`func_table` getter：优先返回 `_func_table`，否则从 `_source_table` + `_has_neg()` 推导。
`source_table` getter：优先返回 `_source_table`，否则从 `_func_table` + `_has_neg()` 推导。

两个 getter 都不应在「另一个也空」时短路返回空值——空的 DataFrame 取反仍是空，不妨碍后续逻辑。

### 4. 不 copy 数据

`_merge_ic_result` 写入 `r.func_table` 时不应 `.copy()`——让 `pd.DataFrame` 的 CoW（Copy-on-Write）机制处理内存共享，避免不必要的内存开销。

## 后果

- $Rev 因子与无 $Rev 因子在 intermediate 缓存中正确区分（structural_key 不同）
- 分组测试中两者返回正确结果
- 无 neg 的因子 evaluate 路径中，$Rev/无 $Rev 因子仍可共享 `source_table`（因为 `source_table` 语义就是无 $Rev 的原始数据）
