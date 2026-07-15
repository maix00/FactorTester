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
5. If a platform gap appears, including incomplete FactorExpr operator coverage
   or wrong operator semantics, record it, fix FactorTester, validate, then
   resume.

The harness calls the real `factortester` CLI. It does not require the user's
machine to have FactorTester server source code. Factor-family names such as
`SgCCS` are ordinary option values, never subcommands or defaults.

## Commands

```bash
cli-anything-factortester-research doctor --json
cli-anything-factortester-research plan --factor-family SgCCS --template '2026-06-02 07:20:47' --product-group 中国期货日盘 --n 2m --f 1m --rev --json
factortester custom_factors operators
cli-anything-factortester-research workspace prepare --build --sync --json
cli-anything-factortester-research workspace inspect --factor-family SgCCS --json
cli-anything-factortester-research run-step -- ic_test grid --factor-family SgCCS --product-group 中国期货日盘 --n 2m --f 1m --rev
factortester custom_factors factor-library history --factor-family SgCCS --product-group 中国期货日盘
factortester custom_factors factor-library rank --preset ic-stable --start-date 2024-01-01 --end-date 2025-12-31
factortester custom_factors factor-library rank --preset costed-backtest --start-date 2024-01-01 --end-date 2025-12-31
factortester custom_factors factor-library import-result --dir /path/to/research_reports/factors/MyFamily --report-path /path/to/report.md --note 'backfill existing artifacts'
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
- Before editing a factor, inspect backend FactorExpr operators with
  `factortester custom_factors operators`.
- If the needed FactorExpr operator is missing or incomplete, record its
  semantics, input/output signature, no-look-ahead constraints, and validation
  tests, then fix the owning platform branch/worktree before continuing.
- Do not run IC/type/backtest before preparing and inspecting the factor
  workspace. If no workspace exists, build it first with
  `workspace prepare --build --sync`.
- Treat missing CLI/backend features as codebase gaps, not research conclusions.
- Before repeating expensive diagnostics, query `factor-library history` and
  `factor-library rank`. Backfill old JSON artifacts with
  `factor-library import-result --artifact ...` or `--dir ...`.
- Result-library ranking is candidate generation only. Ranked factors still need
  validation slices, transaction costs, capacity, and OOS review.
- Product-group labels stored in research results are not automatically product
  group candidates; create or import real product groups before using them in new
  tests.
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
