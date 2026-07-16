---
name: cli-anything-factortester-research
description: Use the FactorTester CLI through a CLI-Anything research harness for factor IC, type analysis, backtest grids, result audits, and codebase gap tracking.
---

# FactorTester Research Harness

This packaged copy mirrors the canonical repo-root skill at
`skills/cli-anything-factortester-research/SKILL.md`.

Use `cli-anything-factortester-research` to plan and run rigorous FactorTester
factor research through the real `factortester` CLI. Factor-family names such as
`SgCCS` are ordinary values, never commands or defaults. The harness records
platform gaps and pauses research when FactorTester needs codebase improvement,
including missing FactorExpr operators, incomplete operator coverage, wrong
operator semantics, and incorrect calculations.

Key commands:

```bash
cli-anything-factortester-research doctor --json
cli-anything-factortester-research plan --factor-family SgCCS --product-group 中国期货日盘 --param N=2m --f 1m --rev
factortester custom_factors operators
cli-anything-factortester-research workspace prepare --build --sync --json
cli-anything-factortester-research workspace inspect --factor-family SgCCS --json
cli-anything-factortester-research run-step -- ic_test grid --factor-family SgCCS --product-group 中国期货日盘 --param N=2m
factortester custom_factors factor-library history --factor-family SgCCS --product-group 中国期货日盘
factortester custom_factors factor-library metrics
factortester custom_factors factor-library rank --preset ic-stable --start-date 2024-01-01 --end-date 2025-12-31
factortester custom_factors factor-library rank --preset costed-backtest --start-date 2024-01-01 --end-date 2025-12-31
factortester custom_factors factor-library import-result --dir /path/to/research_reports/factors/MyFamily --report-path /path/to/report.md --note 'backfill existing artifacts' --sample-role oos --regime-label low_vol --slice-name 2026Q1
factortester custom_factors factor-library save-result --factor-family MyFamily --factor-alias 'MyFamily|N:20' --test-type ic --start-date 2026-01-01 --end-date 2026-01-31 --metric ic_mean=0.03 --sample-role oos --regime-label low_vol --slice-name 2026Q1
factortester custom_factors factor-library stability --preset ic-stable --factor-family SgCCS --by quarter
cli-anything-factortester-research operator set --mode source_owner --admin-port 7998
cli-anything-factortester-research service restart --target-port 8123 --dry-run --json
cli-anything-factortester-research gap list --json
cli-anything-factortester-research status --json
```

Server-code gap rule:

- `client_only` users cannot modify FactorTester server source.
- Missing or incomplete FactorExpr operators are platform gaps. Record the
  missing operator semantics, input/output signature, no-look-ahead constraints,
  and validation tests before fixing the owning branch/worktree.
- `source_owner` users must first identify the owning issue/task and edit the
  corresponding branch/worktree. Merge those platform changes into the CLI
  worktree only after tests/commits, then restart through port 7998.

Factor-source rule:

- Before writing or changing factor source, inspect backend FactorExpr operators
  with `factortester custom_factors operators`.
- Before IC/type/backtest diagnostics, run `workspace prepare --build --sync` and
  then `workspace inspect --factor-family <NAME>`.
- Before repeating expensive diagnostics, query `factor-library history` and
  `factor-library rank`. Backfill old JSON artifacts with
  `factor-library import-result --artifact ...` or `--dir ...`.
- Research scripts that already have metrics can write directly with
  `factor-library save-result` instead of creating an intermediate artifact.
- Saved runs should carry `sample_role`, `regime_label`, `slice_name`, and
  overfit-audit fields such as `test_count`, `grid_size`, `oos_pass`,
  `multi_product_group_pass`, and `costed_pass` whenever those are known.
- Use `factor-library metrics` as the canonical metric-name registry and
  `factor-library stability` before treating a candidate as robust across
  regimes or time slices.
- Result-library ranking is candidate generation only; still run validation
  slices, transaction costs, capacity, and OOS review.
- Product group/product path and product mask are different research controls.
  Product group/path defines the cross-sectional ranking universe and group
  boundaries. Product mask filters products after membership/target construction
  for trading or evaluation. Do not report a masked broad-universe run as if it
  were a reranked narrow-universe product group.
