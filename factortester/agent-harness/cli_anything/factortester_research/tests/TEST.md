# Test Plan

## Inventory

- `test_core.py`: plan generation, validation checklist, session/gap state.
- `test_full_e2e.py`: CLI subprocess behavior using `_resolve_cli()`, JSON output,
  dry-run command construction, and gap recording against a fake factortester
  executable.

## Workflows

### Plan-first factor research

Simulates an agent creating an SgCCS research plan before execution.

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

## Results

Run:

```bash
cd factortester/agent-harness
python -m pytest cli_anything/factortester_research/tests -v --tb=no
```

Validated in GTHT environment:

```text
.......                                                                  [100%]
7 passed in 0.55s
```

Installed-command validation:

```bash
python -m pip install -e .
CLI_ANYTHING_FORCE_INSTALLED=1 python -m pytest cli_anything/factortester_research/tests -q
```

```text
.......                                                                  [100%]
7 passed in 0.99s
```

Manual command smoke test:

```bash
cli-anything-factortester-research --session /tmp/ftr-session.json plan \
  --factor-family SgCCS \
  --template '2026-06-02 07:20:47' \
  --product-group 中国期货日盘 \
  --n 2m --f 1m --rev --json
```

Verified that `SgCCS` is passed as a factor-family value, not registered as a
command, and that the plan orders IC/type diagnostics before group backtesting.
