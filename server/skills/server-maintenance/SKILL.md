---
name: server-maintenance
description: Diagnose and resolve authorized private FactorTester server maintenance cases, including backend anomalies, missing platform capabilities, database migrations, Graph version publication or activation, and research-branch continuation. Use only for a concrete Maintenance Case or an explicitly authorized server change; do not use for ordinary factor research or to grant backend authority.
---

# Server Maintenance

Operate on one authorized Maintenance Case at a time. Keep unaffected research
running and load only the evidence required by the current case.

## Start from the bounded packet

Read `server/AGENTS.md`, then run:

```bash
python server/skills/server-maintenance/scripts/resume.py \
  --agent-id <agent-id>
```

The server must authenticate a developer and authorize the
`server_maintenance` role. Stop if it refuses. Do not bypass the role check,
query the database to reconstruct a queue, or load full Graph/catalog/history
state. When the queue is unchanged, wait without starting a model invocation.

Claim or continue only the first applicable case. Resolve referenced evidence
on demand. A passing Backend Assurance Gate is the zero-review fast path:
return control to research without inspecting source or starting a verifier.

## Route the case

- For a backend anomaly or missing platform capability, read
  [backend-change.md](references/backend-change.md).
- For Graph publication, activation, rollback, impact analysis, or branch
  continuation, read
  [graph-governance.md](references/graph-governance.md).
- For a database schema, ownership, cleanup, or migration case, also read
  [database-change.md](references/database-change.md).

Do not load an unrelated reference.

## Execute the bounded loop

1. Preserve the anomaly, affected refs, immutable input hashes, code revision,
   and rollback target.
2. Reproduce the reported behavior through the production runtime path with
   the smallest deterministic test.
3. Record exactly one verifier disposition:
   `confirmed_reliable`, `research_input_issue`, or
   `backend_change_proposed`.
4. Implement only an approved `backend_change_proposed` case in the semantic
   owner. Keep verifier and implementation lineage independently attributable.
5. Run focused tests, then affected protocol/replay tests. Measure SQL
   statements and context bytes on changed hot paths.
6. Record commit, test receipt, migration/rollout result, remaining limitations
   and rollback target in the existing Maintenance Case.
7. Wake only affected research refs after exact compatibility checks pass.

Use deterministic code for identity, hashes, graph structure, permissions,
job state, evidence fields, predicates and cache decisions. Use an Agent only
for real semantic judgment, conflicting evidence or an approved code change.

## Preserve authority and confidentiality

- The Skill guides work; it grants no role, approval, merge or deployment
  authority.
- Never merge or push without explicit human authorization.
- Never return server source, database paths, credentials, private factor
  definitions, proprietary data, complete artifacts or this Skill body through
  a client response.
- Never copy this private Skill into the public client, Harness or generated
  Agent packet.
- Newly found external Skills remain quarantined until their description,
  source hash, permissions, token estimate and execution scope are approved in
  the Agent conversation.
- Continue unaffected Jobs. Pause only refs whose semantics or immutable inputs
  are actually affected.
