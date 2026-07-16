# Test Plan

## Inventory

- `test_core.py`: plan generation, validation checklist, session/gap state,
  service target selection, and source-owner worktree routing rules.
- `test_full_e2e.py`: CLI subprocess behavior using `_resolve_cli()`, JSON output,
  dry-run command construction, gap recording against a fake factortester
  executable, operator mode persistence, and client-only service restart guards.

## Workflows

### Plan-first factor research

Simulates an agent creating a research plan for an arbitrary factor family before
execution. The concrete subprocess smoke test uses SgCCS only as an example
factor-family value.

Verified:

- IC test appears before backtest.
- Factor type analysis appears before backtest.
- Cost/capacity-aware backtest grid is included.
- Validation checklist includes transaction cost and gap-repair discipline.

### Codebase gap loop

Simulates a missing FactorTester CLI/backend feature.

Verified:

- `run-step` records the command result.
- Missing feature output creates a gap.
- Session status becomes `code_improvement_required`.
- Resolving the gap returns status to `research_ready`.

### Factor workspace and source-owner loop

Simulates an agent separating writable factor-source improvement from server-code
improvement.

Verified:

- Research plans include FactorExpr operator inspection and factor source
  inspection before diagnostics.
- Research plans query the factor-library result store before diagnostics and
  include `history`, `rank`, and `import-result` commands.
- Research plans include the source-owner platform gap loop.
- `client_only` users cannot restart managed server worktrees.
- `source_owner` persists the 7998 admin port used for service restart.
- Source owners must fix platform code in the owning issue branch/worktree
  before merging it into the CLI worktree.

## Results

Run:

```bash
cd tools/cli/agent-harness
conda run -n GTHT pytest cli_anything/factortester_research/tests -q
```

Validated in GTHT environment:

```text
...............                                                          [100%]
15 passed in 0.92s
```

Installed-command validation:

```bash
python -m pip install -e .
CLI_ANYTHING_FORCE_INSTALLED=1 conda run -n GTHT pytest cli_anything/factortester_research/tests/test_full_e2e.py -q
```

```text
.......                                                                  [100%]
7 passed in 0.84s
```

Scope note: this is a CLI-Anything adaptation for a remote HTTP research client.
It intentionally validates session state, subprocess command behavior, real
`factortester` CLI delegation, gap handling, workspace/source inspection, and
7998 service-restart planning. It does not validate local GUI preview/export
features because FactorTester research runs are not local document-rendering
workflows.

Manual command smoke test:

```bash
cli-anything-factortester-research --session /tmp/ftr-session.json plan \
  --factor-family SgCCS \
  --template '2026-06-02 07:20:47' \
  --product-group 中国期货日盘 \
  --param N=2m --f 1m --rev --json
```

Verified that `SgCCS` is passed as a factor-family value, not registered as a
command, and that the plan orders IC/type diagnostics before group backtesting.

Additional smoke tests:

```bash
cli-anything-factortester-research --session /tmp/ftr-harness-service.json \
  operator set --mode source_owner --admin-port 7998 --json

cli-anything-factortester-research --session /tmp/ftr-harness-service.json \
  service restart --target-port 8123 --dry-run --json
```

Verified the dry-run resolved the issue-123 managed worktree on port 8123 and
planned stop/start actions through the 7998 manager.

```bash
cli-anything-factortester-research --session /tmp/sgccs-harness.json \
  workspace inspect --factor-family SgCCS --no-sync --json
```

Verified SgCCS source was found in the factor workspace before diagnostics.
