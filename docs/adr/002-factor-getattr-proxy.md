# ADR-002：Factor.__getattr__ 透明代理策略

- **日期**：2026-05-12
- **状态**：已接受
- **决策者**：FactorTester 团队

---

## 背景

`Factor` 实例包装一个 `FactorExpr`（`self._expr`），外部代码有时需要直接在 Factor 上调用 FactorExpr 的 DSL 方法（如 `factor.rolling_mean(N)`、`factor.cs_rank()` 等）。

实现方式有两种：
1. **透明代理**：`Factor.__getattr__` 将未命中属性转发到 `self._expr`
2. **显式暴露**：Factor 提供 `self.expr` 属性，外部写 `factor.expr.rolling_mean(N)`

## 决策

**保留 `__getattr__` 透明代理，使用排除列表而非白名单。**

### 排除列表

以下属性绝不代理到 `self._expr`：

```
'_expr', '_initialized', '_func_expr', '_source_expr',
'_data', '_source_data', '__eq__', '__hash__'
```

**排除原因：**

| 属性 | 原因 |
|------|------|
| `_expr` | 循环引用，导致无限递归 |
| `_initialized` | `__new__` 中 `hasattr()` 调用会触发 `__getattr__` |
| `_func_expr`, `_source_expr`, `_data`, `_source_data` | Factor 自己的内部属性，不可代理 |
| `__eq__` | `FactorExpr.__eq__` 返回 `CompositeExpr`（表达式构造语义），会破坏 dict/set 的 key 协议和 `unittest` 断言 |
| `__hash__` | Factor 显式覆盖为 `hash(name, structural_key)`，不可回退到 `FactorExpr.__hash__`（基于 `id(self)`） |

### 为什么不用白名单？

白名单方案需要每次修改 `FactorExpr` 时同步更新，维护成本高且容易遗漏。排除列表方案天然安全：**所有新增的 `FactorExpr` 公共方法自动可以被代理**，而 Factor 自己定义的属性不会走 `__getattr__`（Python 优先命中实例自身的 `__dict__`）。

### 实际影响

经全代码库搜索，目前 **没有外部代码通过 Factor 实例调用 FactorExpr DSL 方法**，所有 DSL 方法调用都在 `Factors/*.py` 的 `factor_expr()` 静态方法内对 `ParamRef`/`ColumnRef`（FactorExpr 子类）调用。但保留代理作为便捷出口是合理的，不影响安全性。

## 后果

- ✅ 新增 FactorExpr DSL 方法无需修改其他代码即可对 Factor 实例可用
- ✅ 排除列表极短（8 项），易于理解和维护
- ✅ 拼写错误会正确抛 `AttributeError` 而非静默返回错误结果
- ⚠️ `Factor.__eq__` 被显式覆盖为结构等价比较（因为不能走 FactorExpr 的 DSL `==` 语义）
- ⚠️ 未来如 Factor 新增内部属性，需要在排除列表中追加
