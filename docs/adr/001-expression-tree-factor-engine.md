# ADR-001：基于表达式树的因子引擎

- **日期**：2026-05-12
- **状态**：已接受
- **决策者**：FactorTester 团队

---

## 背景

FactorTester 需要一个因子定义系统，满足以下需求：

1. 非程序员也能通过可视化编辑器组合因子
2. 支持 40+ 内置因子，结构统一
3. 在数百品种 × 数百万时间点上高效计算因数值
4. 支持相同子表达式的缓存和去重
5. 自动生成 LaTeX 公式用于文档和 UI 展示

替代方案是每个因子一个命令式 Python 函数，虽然可行，但会使可视化组合、依赖分析和去重都变得非常困难。

## 决策

**采用表达式树 DSL（`FactorExpr`）作为核心因子表示方式。**

### 架构

三层表达式树：

```
第1层 — 叶子节点
  ColumnRef(DataColumn)     → 引用数据列（开盘价、收盘价、成交量等）
  ConstExpr(value)          → 字面常量
  ParamRef(alias)           → 未解析参数（在创建 Factor 时解析）

第2层 — 算子节点
  RollingOp(op, window)     → 时序滚动运算（均值、标准差、最大值等）
  ShiftOp(steps)            → 滞后/领先
  CrossSectionalOp(op)      → 横截面运算（排名、标准化等）

第3层 — 复合表达式
  CompositeExpr(op, a, b)   → 二元：+、-、*、/、>、<、&、|
  OperandExpr(op, x)        → 一元：abs、log、neg、sign、sqrt、~
```

### 声明方式

```python
class MmRet(FactorFamily):
    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        return P.delta('$F') / P.shift('$F')
```

`ParamRef` 节点（`$F`、`$P`）被自动发现，成为因子的可配置参数。调用 `get_factor(F='5d')` 时，所有 `ParamRef` 被解析为 `ConstExpr` / `ColumnRef`，生成 `Factor` — 一个可直接求值的纯表达式树。

### 求值流程

1. 从表达式树构建依赖 DAG
2. 拓扑排序 → 求值顺序
3. 每个节点：从 `product.{freq}` 读取 → 计算 → 缓存结果
4. 信号对齐到目标频率（`SignalAlign`）
5. 可选取反，用于反转因子

### 去重策略

- `Factor` 继承 `UniqueObject` → 相同 `structural_key` = 同一实例
- `FactorData` 注册表（全局，每个 `FactorTester` 一个）按 `structural_key` 缓存表达式结果
- `IdleResourceManager` 缓存原始 DataFrame，5 分钟 TTL

## 后果

### 正面影响

- **可视化编辑器支持**：表达式树与自定义因子编辑器中的 DAG 节点一一对应
- **LaTeX 生成**：`to_latex()` 递归遍历树 → 公式渲染
- **依赖分析**：`param_deps`、`dependencies`、`ordered_param_deps` 均可从树结构推断
- **去重**：相同子表达式只计算一次
- **声明式**：新增因子只需写 `factor_expr()`，无需命令式代码

### 负面 / 权衡

- **签名脆弱性**：修改基类节点的 `evaluate()` 签名时需同步更新所有调用方（`RollingOp`、`ShiftOp` 等）— 不匹配导致运行时 `TypeError`
- **命名冲突**：`as_intermediate(name)` 要求名称唯一；冲突直接报错而非自动加后缀，避免数据查找歧义
- **多品种解析**：对于密集/同会话面板，`Timedelta` / `DataFreq` 窗口可按产品可用的 bars 解析；对于不同交易时段品种的统一面板，本条原有的按各产品 `day_periods` 解析规则已由 [ADR-007](007-session-aware-window-semantics.md) 取代
- **缓存过期**：纯表达式的全局中间缓存可能在不同品种集合间保留旧 `source_table`；重用时必须刷新
- **类标记继承**：基类的 `hide` 标记若通过 `getattr` 继承，会意外隐藏具体子类；仅基类标记须用 `cls.__dict__` 检查

## 考虑过的替代方案

1. **命令式逐因子函数**：初期更简单，但使可视化组合、依赖分析、LaTeX 生成和去重都变得极其困难
2. **YAML/JSON 因子定义**：能做简单组合，但无法表达复杂因子逻辑（条件分支、滚动相关等）
3. **SymPy 符号数学**：过于笨重；无法天然表达时序/横截面运算

## 参考

- `tools/factors/FactorExpr.py` — 表达式树实现
- `tools/factors/FactorFamily.py` — FactorFamily 基类
- `tools/factors/Factors.py` — Factor（已解析表达式 + 缓存）
- `tools/factors/FactorTester.py` — 回测驱动 + FactorData 注册表
- `CONTEXT.md` — 领域语言与约定
