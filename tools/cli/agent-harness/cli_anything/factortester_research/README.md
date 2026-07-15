# cli-anything-factortester-research

Agent-native harness for FactorTester factor research.

## Install

```bash
cd tools/cli/agent-harness
python -m pip install -e .
```

The real backend dependency is the separately installed `factortester` CLI. It
must be configured to point at a running FactorTester server.

```bash
factortester configure --host 127.0.0.1 --port 8123
factortester login --username <user>
cli-anything-factortester-research doctor
```

## Research Flow

`SgCCS` below is only an example factor-family value. The harness is designed
for any server-registered or workspace-defined factor family.

```bash
cli-anything-factortester-research plan \
  --factor-family SgCCS \
  --template '2026-06-02 07:20:47' \
  --product-group 中国期货日盘 \
  --n 1m --n 2m --f 1m --rev

cli-anything-factortester-research run-step -- ic_test grid --factor-family SgCCS --product-group 中国期货日盘 --n 2m --f 1m --rev
cli-anything-factortester-research run-step -- factor_type_analysis grid --factor-family SgCCS --product-group 中国期货日盘 --n 2m --f 1m --rev
cli-anything-factortester-research run-step -- backtest compare factor-grid --factor-family SgCCS --product-group 中国期货日盘 --n 2m --f 1m --rev --volume-capacity-mode volume_participation
```

If a command exposes a missing backend/CLI feature, the harness records a gap and
sets the session status to `code_improvement_required`.

Before testing a family, inspect the backend FactorExpr operator registry. If
the desired factor idea needs operators that are missing, record the missing
operator semantics, input/output signature, no-look-ahead constraints, and tests,
then fix the platform in the owning worktree before continuing. After the
operator gate passes, prepare and inspect the factor workspace so the agent knows
what the factor computes. If the workspace has not been built locally,
`prepare --build --sync` is the first step:

```bash
factortester custom_factors operators
cli-anything-factortester-research workspace prepare --build --sync
cli-anything-factortester-research workspace inspect --factor-family SgCCS
```

If research results are poor but the factor workspace is writable, mark the
factor-improvement loop and edit/push the factor source before re-running IC/type
diagnostics:

```bash
cli-anything-factortester-research decision poor-result --reason "IC decay and cost screen failed"
factortester custom_factors workspace git diff
factortester custom_factors workspace push
```

## Research Result Store

The FactorTester CLI writes new IC, factor type, factor evaluation, and backtest
research runs into the factor-library result store. Agents should query this
store before repeating expensive diagnostics, and should backfill older report
artifacts when they become relevant:

```bash
factortester custom_factors factor-library history --factor-family SgCCS --product-group 中国期货日盘

factortester custom_factors factor-library rank \
  --start-date 2024-01-01 --end-date 2025-12-31 \
  --preset ic-stable

factortester custom_factors factor-library rank \
  --start-date 2024-01-01 --end-date 2025-12-31 \
  --preset costed-backtest

factortester custom_factors factor-library import-result \
  --dir /path/to/research_reports/factors/MyFamily \
  --report-path /path/to/research_reports/factors/MyFamily/report.md \
  --note "backfill existing artifacts before candidate ranking"
```

`rank` is a candidate-generation query. A ranked factor still needs validation
slices, cost/capacity checks, and OOS review before it can be treated as a
research result. Product-group names in result records are labels for the tested
configuration; they are not automatically product-group candidates for future
runs unless the product group exists in the product-group library.

If the gap is platform/server code rather than factor source, including missing
FactorExpr operators, wrong operator semantics, or incorrect factor/backtest
calculation, distinguish the operator mode:

```bash
# Client-only users have no server source code and cannot restart the service.
cli-anything-factortester-research operator set --mode client_only

# Source owners can fix code, run tests, then restart the managed worktree via 7998.
cli-anything-factortester-research operator set --mode source_owner --admin-port 7998
cli-anything-factortester-research service list
cli-anything-factortester-research service restart --target-port 8123
```

Source owners still must obey the repository `AGENTS.md` workflow: identify the
owning issue/task and make server-code changes in that issue's branch/worktree.
Those fixes need enough tests to prove the operator semantics or calculation
path is correct before research resumes. The CLI worktree should only receive
those platform changes through an explicit merge after the owning task has tests
and commits. CLI-only harness changes stay in the CLI worktree.

## JSON

All commands intended for agents support `--json`.
