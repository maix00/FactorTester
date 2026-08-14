---
name: factortester-server-maintenance
description: Diagnose and resolve authorized private FactorTester server maintenance cases, including Docker/WireGuard/SSH deployment, while keeping local source work, Manager control, and remote publication under separate authority boundaries. Use only for a concrete Maintenance Case or an explicitly authorized server change; do not use for ordinary factor research or to grant backend authority.
---

# Server Maintenance

Operate on one authorized Maintenance Case at a time. Keep unaffected research
running and load only the evidence required by the current case.

## Classify the operation before requesting server authority

Do not treat every change under `server/` as a remote maintenance operation.
The repository, the local Manager, and the public deployment have separate
authority boundaries:

| Operation | Required authority | Authentication path |
|---|---|---|
| Read, edit, test, and commit the local checkout | The user's repository task authorization | Normal Git/worktree and local process or Docker access |
| Call a protected local Manager endpoint or restart its owned services | An authorized Manager principal, normally `super_admin` | `factortester manager ...`; the CLI reads its URL-scoped token from macOS Keychain |
| Run the bounded server-maintenance resume/implementation flow | Authenticated developer plus the server-issued maintenance roles | Ordinary FactorTester session cookie through `resume.py`; a Manager token is not a substitute |
| Merge/push a release | Explicit human release authorization and Git credentials | Git remote workflow |
| Publish or reload the remote public server | Explicit deployment authorization, remote administrator access, and the approved Alibaba/Aliyun SSH or Session Manager transport | Deployment wrapper/SSH; never inferred from local source access |

Local source changes, focused tests, and commits must not be blocked merely
because the current checkout contains private backend code. A remote role is
required only when the operation actually invokes a protected server runtime
or changes a deployed system. Merge and publication remain separate actions.

### Use the correct local credential store

The CLI Manager credential is stored under the Keychain service
`com.gtht.factortester.manager`, keyed by the normalized Manager URL. Use the
normal CLI surface to check it without printing its value:

```bash
factortester manager status --json
```

The native Swift client and the CLI may have different Keychain items. The
Swift session credential, native device key, browser cookie, CLI FactorTester
cookie, and CLI Manager bearer token are different credentials and must not be
copied or treated as interchangeable. In particular, `resume.py` uses the
ordinary FactorTester cookie session and therefore may return `401 login
required` even when `factortester manager status` succeeds as `super_admin`.
Never dump Keychain values, passwords, bearer tokens, private keys, or cookie
contents into logs or responses.

## Start from the bounded packet for runtime maintenance only

Read `server/AGENTS.md`, then, only for a protected runtime maintenance case,
run:

```bash
python server/skills/factortester-server-maintenance/scripts/resume.py \
  --agent-id <agent-id>
```

The server must authenticate a developer and authorize the
`server_maintenance` role. Stop if it refuses. Do not bypass the role check,
query the database to reconstruct a queue, or load full Graph/catalog/history
state. When the queue is unchanged, wait without starting a model invocation.
Do not run this packet merely to edit or test local source; use the local
repository workflow for that case.

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
- For Docker, WireGuard, SSH publication, peer-key governance, public release,
  rollback, or container lifecycle, read
  [infrastructure.md](references/infrastructure.md).

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

### Controlled Manager and service restart

The CLI exposes the approved transaction without exposing this private Skill's
body. Use its normal help surface after reading this Skill:

```bash
factortester manager --help
factortester manager restart-fleet --help
```

The help output is descriptive only; it does not authenticate or grant
maintenance authority.

For a local Manager, the command uses the URL-scoped Manager credential already
managed by the CLI. Confirm the principal with `factortester manager status`
before a mutating action. This local Manager authority is not Aliyun SSH
authority and does not authorize a public deployment.

When a server source change needs the local fleet reloaded, use the shared
Manager transaction rather than stopping ports manually:

```bash
factortester manager restart-fleet \
  --source-root /absolute/path/to/the/server-worktree \
  --source-mode worktree --yes --json
```

Use `--source-mode git-commit --source-revision <full-40-char-sha>` when the
running Manager must come from an exact committed checkout. The two modes are
exclusive and never fall back to one another. The command snapshots all
currently running Manager-owned instances, closes them using `wait` by
default, restarts Manager, waits for its authenticated session and restores
the same instances. Use `--stop-mode force` only with explicit authorization;
an individual override such as `--port-stop-mode 8141=force` is allowed when a
single port cannot drain. A failed transaction attempts the captured-set
rollback and reports the exact affected instances.

### Remote publication is a separate release operation

Only after the source change has been reviewed, committed, and explicitly
approved for release may the deployment workflow be entered. It requires the
separate remote administrator/Aliyun transport authorization, transfers the
selected full Git revision, and verifies the remote release. Do not use a
local Manager Keychain token as a substitute for the remote transport
credential, and do not make the public server fetch GitHub itself.

## Preserve authority and confidentiality

- The Skill guides work; it grants no role, approval, merge or deployment
  authority. Local repository edits do not require the server-maintenance role;
  protected runtime actions and remote publication do.
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
