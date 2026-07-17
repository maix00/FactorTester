# Harness Test Plan

The harness tests cover:

- plan generation through `workspace -> immutable RunSpec -> job`;
- absence of analysis-specific submission commands and `page_uuid` ownership;
- session/gap state transitions;
- validation slice separation;
- source-owner worktree selection;
- subprocess delegation to the real `factortester` executable.

Run:

```bash
cd tools/cli/agent-harness
conda run -n GTHT pytest cli_anything/factortester_research/tests -q
```

Installed-command validation:

```bash
python -m pip install -e .
CLI_ANYTHING_FORCE_INSTALLED=1 conda run -n GTHT pytest cli_anything/factortester_research/tests/test_full_e2e.py -q
```

Manual smoke test:

```bash
cli-anything-factortester-research --session /tmp/ftr-session.json plan \
  --factor-family SgCCS \
  --factor 'SgCCS=SgCCS|P:CA|N:10d' \
  --configuration-file research-configuration.json \
  --json
```

The generated plan must create/select a workspace, write or import a revision, submit one run containing requested analyses, and observe/control results by `job_id`.

## External Vibe infrastructure coverage

- Unit coverage validates the canonical locked pipeline command, daily/minute
  manifest contracts, factor provenance, mandatory next-bar execution, and the
  explicit unavailable GTHT import boundary.
- The real-file smoke test validated the existing daily v1, minute v1,
  `academic_carhart_mom`, and `gtht_handoff.json` artifacts.

Latest result:

```text
.................                                                        [100%]
17 passed in 1.52s
```
