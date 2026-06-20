# ADR-010: Factor IR — 单一因子定义，多框架编译

**日期**: 2025-07-14  
**状态**: 已采纳  
**决策者**: 用户 + Copilot

---

## 背景

FactorTester 目前有两套写因子的方法：

| 方法 | 表达方式 | 代表框架 |
|------|---------|---------|
| 表达式树（FactorExpr） | Python 算子组合 | FactorTester 自身 |
| 公式字符串 | `"EMA($close,12)-EMA($close,26)"` | QLib |
| 事件驱动类 | `class MACD(bt.Indicator)` | BackTrader |

用户需要在不同回测/研究框架之间迁移因子，但目前只能人工翻译。三个框架的算子虽然名称不同（`rolling_mean` vs `EMA` vs `EMA`），但核心语义完全一致。

**核心问题**：如何定义一次因子，就能自动输出到 QLib 表达式字符串、BackTrader Indicator 类、以及 FactorTester 自身的表达式树？

---

## 决策

**采用单一因子定义系统（FactorExpr 算子树）+ 中间表示（Factor IR）+ 多框架编译器。**

```
用户写一次 ──→ FactorExpr 表达式树
                  │
                  ├── to_ir() → dict (Factor IR)
                  │                │
                  │                ├── QLibCompiler   → "EMA(CLOSE,12)-EMA(CLOSE,26)"
                  │                ├── BackTraderCompiler → class MACD(bt.Indicator)
                  │                └── FactorTesterCompiler → 原生 evaluate()
                  │
                  ├── _structural_key() → tuple  (缓存去重，性能关键路径)
                  ├── _to_latex()       → LaTeX (论文渲染)
                  └── _get_alias()      → 字符串别名 (UI 展示)
```

### 为什么不是两套独立的写因子系统

1. **算子 1:1 映射**。三个框架的算子只是命名不同，不存在语义差异。维护两套会带来算子交叉表的一致性问题。
2. **声明式 DSL 有分析优势**。表达式树可以做：自动可视化、LaTeX 导出、结构去重、参数搜索、梯度分析。事件驱动的类语法不支持这些。
3. **事件驱动只是执行模式，不是定义模式**。BackTrader 的 `next()` 方法是一种求值策略，可以从表达式树自动生成。

---

## Factor IR 设计

### 与 `_structural_key` 的关系

`_structural_key` 是 Factor IR 的**同源结构**。两者都是对同一棵表达式树的递归遍历：

| 维度 | `_structural_key` | Factor IR |
|------|-------------------|-----------|
| 格式 | Python `tuple` | Python `dict`（可 JSON 化） |
| 用途 | 去重 + 缓存（性能关键路径） | 跨框架导出 |
| 可序列化 | ❌ 含 Python 对象 | ✅ 纯数据 |
| 扩展性 | 加字段需改索引 | 加字段不影响编译器 |

**决策**：保留 `_structural_key` 不动（它是 FactorData 查找的关键路径，tuple 格式最优），新增 `to_ir()` 方法输出 dict。

`to_ir()` 复用 `_structural_key` 的遍历架构：
- 对称算子（`add, mul, max, min, and, or, eq, ne`）对子节点排序，保证 `a+b ≡ b+a`
- `_structural_extra()` 对应 IR 中的额外属性

### IR 格式（示例）

```json
// ROE.chg(5).rolling_mean(20).cs_zscore()
{
  "type": "cross_sectional",
  "op": "cs_zscore",
  "operand": {
    "type": "rolling",
    "op": "mean",
    "data": {
      "type": "composite",
      "op": "sub",
      "children": [
        {"type": "shift", "op": "shift", "periods": 0,
         "operand": {"type": "column", "field": "ROE"}},
        {"type": "shift", "op": "shift", "periods": -5,
         "operand": {"type": "column", "field": "ROE"}}
      ]
    },
    "window": 20
  }
}
```

### 叶子节点 IR

| FactorExpr 节点 | IR `type` | IR 字段 |
|----------------|-----------|--------|
| `ColumnRef(col)` | `"column"` | `{"type":"column","field":"CLOSE"}` |
| `ParamRef(param)` | `"param"` | `{"type":"param","alias":"W","default":"20"}` |
| `ConstExpr(42)` | `"const"` | `{"type":"const","value":42}` |
| `ConstExpr(DataFreq("5d"))` | `"const"` | `{"type":"const","value":"5d"}` |

### 算子节点 IR

| FactorExpr 算子 | IR `op` | IR 字段 |
|----------------|---------|--------|
| `CompositeExpr("add", a, b)` | `"add"` | `{"op":"add","children":[a,b]}` |
| `CompositeExpr("mul", a, b)` | `"mul"` | `{"op":"mul","children":[a,b]}` |
| `CompositeExpr("div", a, b)` | `"div"` | `{"op":"div","children":[a,b]}` |
| `CompositeExpr("neg", a)` | `"neg"` | `{"op":"neg","operand":a}` |
| `CompositeExpr("log", a)` | `"log"` | `{"op":"log","operand":a}` |
| `RollingOp("mean", data, window)` | `"rolling_mean"` | `{"op":"rolling_mean","data":...,"window":20}` |
| `RollingOp("std", data, window)` | `"rolling_std"` | `{"op":"rolling_std","data":...,"window":20}` |
| `ShiftOp(data, periods)` | `"shift"` | `{"op":"shift","operand":...,"periods":-5}` |
| `CrossSectionalOp("cs_zscore", x)` | `"cs_zscore"` | `{"op":"cs_zscore","operand":x}` |
| `CrossSectionalOp("cs_rank", x)` | `"cs_rank"` | `{"op":"cs_rank","operand":x}` |
| `TermStructureOp("term_spread", near, far)` | `"term_spread"` | `{"op":"term_spread","near":...,"far":...}` |
| `SignalAlign(data, freq, ...)` | `"signal_align"` | `{"op":"signal_align","data":...,"freq":"1d","basepoint":...}` |

---

## 框架编译器映射

### QLib 编译器（目标：表达式字符串）

| Factor IR `op` | QLib 表达式 |
|---------------|------------|
| `column` | `$field`（如 `$close`） |
| `const` | 字面量（如 `20`） |
| `add` | `a + b` |
| `sub` | `a - b` |
| `mul` | `a * b` |
| `div` | `a / b` |
| `neg` | `-a` |
| `abs` | `Abs(a)` |
| `log` | `Log(a)` |
| `rolling_mean` | `Mean(a, window)` |
| `rolling_std` | `Std(a, window)` |
| `rolling_sum` | `Sum(a, window)` |
| `rolling_min` | `Min(a, window)` |
| `rolling_max` | `Max(a, window)` |
| `rolling_corr` | `Corr(a, b, window)` |
| `shift` | `Ref(a, periods)` |
| `cs_zscore` | `(a - Mean(a)) / Std(a)`（QLib 无原生 cs_zscore） |
| `cs_rank` | `Rank(a)` |
| `max` | `Max(a, b)` |
| `min` | `Min(a, b)` |

### BackTrader 编译器（目标：Indicator 类）

| Factor IR `op` | BackTrader Indicator |
|---------------|---------------------|
| `column` | `self.data.close` |
| `const` | 内联常数 |
| `add` | `a + b` |
| `sub` | `a - b` |
| `mul` | `a * b` |
| `div` | `a / b` |
| `rolling_mean` | `bt.indicators.SMA(data, period=window)` |
| `rolling_std` | `bt.indicators.StandardDeviation(data, period=window)` |
| `rolling_ema` | `bt.indicators.EMA(data, period=window)` |
| `shift` | `data(-periods)` |
| `cs_zscore` | 需手动实现（BackTrader 不支持原生横截面） |
| `cs_rank` | 需手动实现 |
| `max` | `bt.Max(a, b)` |
| `min` | `bt.Min(a, b)` |

### 不支持的算子处理

对于目标框架不原生支持的算子（如 `cs_zscore`→BackTrader），编译器有两种策略：
1. **展开为子算子组合**（如 `cs_zscore = (x - cs_mean(x)) / cs_std(x)`）
2. **标记为 `unsupported`**，提示用户手动实现

---

## 后果

### 正面

- **因子可移植**。用户在 FactorTester 写一次，自动得到 QLib 表达式和 BackTrader 类
- **可扩展**。新框架只需增加一个编译器，不改因子定义
- **去重不损失**。`_structural_key` 保持 tuple 格式，`to_ir()` 是额外输出
- **可分析**。IR dict 可被 AI agent 读取，自动生成文档、对比不同因子的结构相似度

### 负面

- **每节点需实现两套遍历**（`_structural_key()` + `to_ir()`），有维护成本
  - 缓解：`OperandExpr.to_ir()` 可实现为默认方法，叶子节点只需覆盖少数实现
- **IR 与 native 求值可能漂移**。如果编译器实现有 bug，IR 输出的表达式可能与 FactorTester 原生结果不一致
  - 缓解：CI 中跑交叉验证（同一因子三个框架求值结果对比）
- **部分算子无法完美映射**。`cs_zscore` 在 QLib 中需展开，`term_spread` 在 BackTrader 无等价物
  - 缓解：标记不支持并提示替代方案

---

## 被考虑的替代方案

### A. 两套独立的写因子系统
维护 FactorExpr DSL + BackTrader 类两套代码。  
**否决**：算子 1:1 映射，重复维护不可接受；且表达式树有分析优势不可放弃。

### B. 直接用 Python 字符串做 IR
如 `"rolling_mean(shift(CLOSE,0)-shift(CLOSE,-5), 20)"` 作为 IR。  
**否决**：字符串解析脆弱、不支持中间变量、AI 无法分析结构。

### C. 直接用 `_structural_key` 的 tuple 做 IR
将 `('RollingOp', 'mean', ...)` 作为跨框架 IR。  
**否决**：tuple 不可 JSON 序列化、人类不可读、加字段需改索引、无法跨语言。

---

## 实施路径

1. **Phase 1: IR 基架** — 在 `FactorExpr` 基类新增 `to_ir() → dict` 抽象方法，每个节点实现
2. **Phase 2: QLib 编译器** — 实现 `QLibCompiler.compile(ir) → str`
3. **Phase 3: 交叉验证** — CI 中验证 FactorTester native 结果 vs QLib 表达式结果
4. **Phase 4: BackTrader 编译器** — 实现 `BackTraderCompiler.compile(ir) → class`
5. **Phase 5: 文档 + AI 工具** — AI agent 可自动读取 IR 生成因子文档
