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
cli-anything-factortester-research workspace prepare --build --sync --json
cli-anything-factortester-research workspace inspect --factor-family SgCCS --json
cli-anything-factortester-research run-step -- ic_test grid --factor-family SgCCS --product-group 中国期货日盘 --n 2m --f 1m --rev
cli-anything-factortester-research decision poor-result --reason 'IC/cost diagnostics failed'
cli-anything-factortester-research operator set --mode client_only
cli-anything-factortester-research operator set --mode source_owner --admin-port 7998
cli-anything-factortester-research service restart --target-port 8123 --dry-run --json
cli-anything-factortester-research gap list --json
cli-anything-factortester-research gap resolve gap-1 --note 'implemented and tested'
cli-anything-factortester-research status --json
cli-anything-factortester-research checklist
```

## Agent Rules

- Do not jump straight to group backtest. Run IC/type diagnostics first.
- Do not run IC/type/backtest before preparing and inspecting the factor
  workspace. If no workspace exists, build it first with
  `workspace prepare --build --sync`.
- Treat missing CLI/backend features as codebase gaps, not research conclusions.
- Track the number of hypotheses tested when sweeping factor/product grids.
- Include transaction costs, capacity, and explicit margin mode before claiming a
  factor is profitable.
- If `status` is `code_improvement_required`, stop research and fix FactorTester
  before continuing.
- `client_only` users cannot edit server code. They may edit writable factor
  workspace source/parameters, but server-code gaps must be exported for a source
  owner.
- `source_owner` users must run tests after code changes and restart the target
  service through the local 7998 manager before retrying failed research steps.
- `source_owner` does not mean "edit platform code in the CLI worktree". First
  identify the owning issue/task, fix and commit in that branch/worktree, then
  merge those platform changes into the CLI worktree when the CLI needs them.
