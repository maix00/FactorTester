---
name: cli-anything-factortester-research
description: Use the FactorTester CLI through a CLI-Anything research harness for factor IC, type analysis, backtest grids, result audits, and codebase gap tracking.
---

# FactorTester Research Harness

This packaged copy mirrors the canonical repo-root skill at
`skills/cli-anything-factortester-research/SKILL.md`.

Use `cli-anything-factortester-research` to plan and run rigorous FactorTester
factor research through the real `factortester` CLI. The harness records platform
gaps and pauses research when FactorTester needs codebase improvement.

Key commands:

```bash
cli-anything-factortester-research doctor --json
cli-anything-factortester-research plan --factor-family SgCCS --product-group 中国期货日盘 --n 2m --f 1m --rev
cli-anything-factortester-research workspace prepare --build --sync --json
cli-anything-factortester-research workspace inspect --factor-family SgCCS --json
cli-anything-factortester-research run-step -- ic_test grid --factor-family SgCCS --product-group 中国期货日盘 --n 2m
cli-anything-factortester-research operator set --mode source_owner --admin-port 7998
cli-anything-factortester-research service restart --target-port 8123 --dry-run --json
cli-anything-factortester-research gap list --json
cli-anything-factortester-research status --json
```

Server-code gap rule:

- `client_only` users cannot modify FactorTester server source.
- `source_owner` users must first identify the owning issue/task and edit the
  corresponding branch/worktree. Merge those platform changes into the CLI
  worktree only after tests/commits, then restart through port 7998.

Factor-source rule:

- Before IC/type/backtest diagnostics, run `workspace prepare --build --sync` and
  then `workspace inspect --factor-family <NAME>`.
