# 架构深化 TODO (索引)

> 来源：`improve-codebase-architecture` skill 扫描结果（2026-05-12）
> 跟踪：GitHub Issues → [maix00/FactorTester](https://github.com/maix00/FactorTester/issues)
> 流程：见 [AGENTS.md](AGENTS.md) — Issue 驱动的开发工作流

---

## ✅ 1. ~~移除 `Factor.__getattr__` 隐式代理~~ → [ADR-002](docs/adr/002-factor-getattr-proxy.md)

决定：保留 `__getattr__`，使用排除列表（8项）。无外部调用者，保留作为便捷出口。

## ⬜ 2. `FactorTester` 8 字典 → `FactorRunResult`  
   [Issue #1](https://github.com/maix00/FactorTester/issues/1) — `tools/factors/FactorTester.py`

## ⬜ 3. `evaluate()` 签名统一为 `EvaluateContext`  
   [Issue #2](https://github.com/maix00/FactorTester/issues/2) — `tools/factors/FactorExpr.py`

## ⬜ 4. `_active_tester` ContextVar → 显式参数  
   [Issue #3](https://github.com/maix00/FactorTester/issues/3) — `tools/factors/FactorTester.py`, `tools/data/DataMeta.py`

## ⬜ 5. 统一重复的图遍历逻辑  
   [Issue #4](https://github.com/maix00/FactorTester/issues/4) — `tools/factors/FactorExpr.py`, `tools/factors/Factors.py`

## ⬜ 6. `$` 前缀规范化 — 内部统一用 `$F`  
   [Issue #5](https://github.com/maix00/FactorTester/issues/5) — `tools/factors/FactorFamily.py`
