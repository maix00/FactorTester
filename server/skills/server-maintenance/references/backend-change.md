# Backend anomaly and capability change

## Diagnose

1. Bind the case to its anomaly code, affected refs, backend build/config
   receipt and immutable research inputs.
2. Trace the real runtime route from public request or scheduler entry through
   the semantic owner to the persisted result. Existing code that is not on
   this route is not evidence of working capability.
3. Reproduce with a focused command or test. Compare trusted invariants before
   reading broad source areas.
4. Prefer deterministic receipt checks. Start a Backend Verifier only when a
   concrete contradiction, impossible invariant, reproducible anomaly or
   material result discrepancy remains.

## Decide

- `confirmed_reliable`: the backend receipt and invariants pass; resume the
  research ref without code work.
- `research_input_issue`: configuration, data, factor source or unsupported
  scope caused the observation; report the exact bounded correction.
- `backend_change_proposed`: source behavior is reproducibly wrong or a
  required approved capability is absent. Bind the proposal to expected
  semantics, files/owner, tests, cost, compatibility and rollback.

Do not turn a weak result into a backend anomaly. Do not let a backend fix
strengthen a factor Claim; it only changes evidence eligibility and may require
new runs.

## Implement and return

Implement at the deepest semantic owner rather than a presentation caller.
Preserve the failing fixture and old receipt. Return a source-free result with:

- case/task ID and disposition;
- old/new build or protocol hashes;
- affected and unaffected refs;
- tests and invariant outcomes;
- whether old Evidence is eligible, limited or reference-only;
- whether a new Job/Run is mandatory;
- rollout and rollback refs.
