---
name: cli-anything-factortester-research
description: Use the FactorTester CLI through a CLI-Anything research harness for factor IC, type analysis, backtest grids, result audits, and codebase gap tracking.
---

# FactorTester Research Harness

Use `cli-anything-factortester-research` when an agent is researching a factor
with FactorTester and needs a disciplined loop:

1. Create an explicit research plan.
2. Run IC/IR and factor-type diagnostics before group backtests.
3. Run cost/capacity-aware backtest grids.
4. Audit order flow, ledgers, snapshots, and runtime summaries.
5. If a platform gap appears, record it, fix FactorTester, validate, then resume.

The harness calls the real `factortester` CLI. It does not require the user's
machine to have FactorTester server source code.

## Commands

```bash
cli-anything-factortester-research doctor --json
cli-anything-factortester-research plan --factor-family SgCCS --template '2026-06-02 07:20:47' --product-group 中国期货日盘 --n 2m --f 1m --rev --json
cli-anything-factortester-research run-step -- ic_test grid --factor-family SgCCS --product-group 中国期货日盘 --n 2m --f 1m --rev
cli-anything-factortester-research gap list --json
cli-anything-factortester-research gap resolve gap-1 --note 'implemented and tested'
cli-anything-factortester-research status --json
cli-anything-factortester-research checklist
```

## Agent Rules

- Do not jump straight to group backtest. Run IC/type diagnostics first.
- Treat missing CLI/backend features as codebase gaps, not research conclusions.
- Track the number of hypotheses tested when sweeping factor/product grids.
- Include transaction costs, capacity, and explicit margin mode before claiming a
  factor is profitable.
- If `status` is `code_improvement_required`, stop research and fix FactorTester
  before continuing.
