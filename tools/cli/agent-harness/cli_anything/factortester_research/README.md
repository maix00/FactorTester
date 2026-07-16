# cli-anything-factortester-research

Agent harness for the remote FactorTester CLI.

## Setup

```bash
cd tools/cli/agent-harness
python -m pip install -e .
factortester configure --host 127.0.0.1 --port 8123
factortester login --username <user>
cli-anything-factortester-research doctor
```

## Durable Research Flow

Prepare one complete ResearchConfiguration JSON object. Registry-defined shared and per-analysis settings remain open-ended; it must include the factors and every setting needed by the requested analyses.

```bash
cli-anything-factortester-research plan \
  --factor-family SgCCS \
  --factor-family MmRet \
  --factor 'SgCCS=SgCCS|P:CA|N:10d' \
  --configuration-file research-configuration.json

cli-anything-factortester-research run-step -- workspace create --factor-family SgCCS --factor 'SgCCS=SgCCS|P:CA|N:10d'
cli-anything-factortester-research run-step -- workspace load-template <configuration_id>
# Then: workspace update --file research-configuration.json
cli-anything-factortester-research run-step -- run submit --analysis ic --analysis factor_evaluation --analysis factor_type_analysis --analysis backtest
cli-anything-factortester-research run-step -- job list
cli-anything-factortester-research run-step -- job watch <job_id>
```

The harness does not invoke analysis-specific submission APIs. `workspace` owns one editable configuration, an immutable `RunSpec` owns execution input, and `job_id` owns status, progress, cancellation, errors, results, and artifacts. It never treats `page_uuid` as the lifecycle owner.

Saved templates use the same ResearchConfiguration payload as the workspace. Loading one increments the optimistic-lock counter and records provenance; it does not revive page runtime.

## Research Guardrails

- Product group/path defines the ranking universe; product mask filters after membership/target construction.
- Signal visibility, IC forward return, and backtest next-open execution must be aligned.
- Costs, capacity, margin, fee mode, sample role, regime label, slice name, grid size, and `costed_pass` belong in the frozen configuration or result metadata.
- Query existing factor-library records before repeating expensive work.
- A failed job retains traceback; cancellation retains its reason; retry/continue creates a linked new attempt.

## CLI-Anything Adaptation Notes

This is a remote HTTP research client, not a local computation substitute. It records research session state and platform gaps. `client_only` users report gaps; `source_owner` users follow `AGENTS.md`, fix the owning issue worktree, test, commit, and wait for explicit merge authorization.
