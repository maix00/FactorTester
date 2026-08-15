# Compact Research Step Batch 1

## Test inventory plan

- `test_contracts.py`: compact inspect and ephemeral prepare/validate contracts.
- `test_routes.py`: authenticated read-only inspect/prepare HTTP behavior.
- `test_research_step_cli.py`: public CLI JSON and offline validation workflow.

## Behavioral test plan

- Inspect projects only the current Graph node, authoritative Profile/workspace
  binding, current Evidence Action, CAS identities, candidate edges, report
  requirement references, and bounded capability summaries.
- Inspect never exposes a complete Graph, TrialPlan, trace history, stdout,
  stderr, Skill body, factor source, or mutable workspace selector.
- Prepare accepts multiple configuration identities for one Evidence Action.
  Until the immutable configuration snapshot service is available through the
  stable client contract, it returns an explicit capability gap and does not
  fabricate RunSpec hashes or execution readiness.
- Validate is deterministic and offline. It verifies the contract hash,
  Profile/workspace/branch identity, action identity, positive configuration
  revisions, unique configuration requests, and rejects unknown fields.
- All operations are read-only and create no ResearchRun, Job, Evidence,
  report checkpoint, Graph transition, or new database object.

## Regression plan

- Existing local `research-graph next-local` and TrialPlan compatibility tests
  remain green.
- The server route is retained only as a migration read/validation contract;
  it does not calculate the local next step or enforce a token/packet budget.
- CLI tests verify `research step validate` performs no HTTP request.

## Test results

```text
conda run -n GTHT python -m pytest -q \
  tests/server/research_step \
  tests/cli/test_research_step_cli.py \
  tests/server/test_trial_execution_checkpoint_api.py \
  tests/server/test_research_graph_protocol_v2.py

31 passed in 1.04s
```

The batch adds no schema, table, Run, Job, Evidence, report, or transition
write. The immutable configuration snapshot capability remains an explicit
non-executable gap rather than a fabricated RunSpec identity.
