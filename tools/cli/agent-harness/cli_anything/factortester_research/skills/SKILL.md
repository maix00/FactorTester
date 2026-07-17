---
name: cli-anything-factortester-research
description: Use durable FactorTester workspaces, immutable runs, and queryable jobs through the real remote CLI.
---

# FactorTester Research Harness

Use one execution contract for IC, factor evaluation, factor type analysis, and backtest:

```bash
cli-anything-factortester-research plan --factor-family SgCCS --factor 'SgCCS=SgCCS|P:CA|N:10d' --configuration-file research-configuration.json
factortester workspace create --factor-family SgCCS --factor 'SgCCS=SgCCS|P:CA|N:10d'
factortester workspace templates
factortester workspace load-template <configuration_id>
factortester workspace update --file research-configuration.json
factortester run submit --analysis ic --analysis factor_evaluation --analysis factor_type_analysis --analysis backtest
factortester job list
factortester job watch <job_id>
factortester job status <job_id>
```

The complete RunSpec must freeze the ranking universe, product mask, factor aliases, dates, costs, capacity, margin mode, fee mode, and sample metadata such as `sample_role`, `regime_label`, `slice_name`, `grid_size`, and `costed_pass`.

Never submit directly to an analysis endpoint and never use `page_uuid` as job ownership. Browser leases only control observer-bound cancellation; CLI jobs are durable. Retry and step continuation create a new linked job attempt.

Before execution, inspect FactorExpr operators and source. Treat missing operators, wrong time alignment, incomplete error/result retention, or broken job lifecycle as platform gaps. Source owners fix the assigned issue worktree under `AGENTS.md`; client-only users retain evidence and report it.

For external Vibe factors, use `external-factor plan` to freeze both daily and
minute panel preparation, then `external-factor validate` on every dataset and
factor manifest. Keep cross-market outputs `experimental_unvalidated`, require
next-bar execution, and report the missing GTHT precomputed FactorRunResult
import boundary as a platform gap rather than bypassing native signal alignment.
