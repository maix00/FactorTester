# cli-anything-factortester-research

Agent-native harness for FactorTester factor research.

## Install

```bash
cd factortester/agent-harness
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

## JSON

All commands intended for agents support `--json`.
