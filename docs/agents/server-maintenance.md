# Server Maintenance Agent Contract

## Entry conditions

Start this flow only for a concrete backend anomaly, unresolved capability gap,
approved backend change, migration, or high-risk graph change. A passing
Backend Assurance Gate is the deterministic fast path: continue research
without a verifier or LLM review.

The authenticated account must be a developer. The server, not the client,
authorizes `server_maintenance`, `backend_verifier`, `implementation_agent`,
and `server_backend_code`. Ordinary sessions may submit bounded anomaly
evidence but cannot claim these roles.

## Bounded startup

1. Claim one Maintenance Case and request its compact `server_maintenance`
   resume packet.
2. Read only the anomaly codes, affected references, approved change
   references, budget summary, and exact runtime evidence needed for the case.
3. Resolve referenced artifacts on demand. Do not load the full Active Graph,
   capability catalog, database, stdout, source tree, or Skill bodies into the
   Agent context.

This startup is provider-neutral. Runtime and model IDs describe an invocation;
they never define the Agent's durable identity or authority.

## Diagnose before changing code

Trace the production runtime path and reproduce the anomaly with the smallest
deterministic test. Use the existing `diagnose` capability description when it
matches. Following cli-anything semantics, prefer a stable command surface and
machine-readable receipts over direct ad-hoc object manipulation.

The Backend Verifier records exactly one of:

- `confirmed_reliable`;
- `research_input_issue`;
- `backend_change_proposed`.

Only the last disposition can open implementation work. The verifier and
implementation Agent must have independent principal and lineage identities.

## Skill and capability gaps

The server stores capability descriptions and approved source hashes, not
downloaded Skill bodies. Search only when the current case lacks a required
capability. Show the proposed Skill description, source, hash, permissions,
token estimate, and affected flow in the Agent conversation. Execution of a
new Skill requires approval there.

If no suitable Skill exists, create or revise one according to skill-creator:
keep `SKILL.md` concise, put detailed references or scripts in dedicated
folders, load them progressively, validate the package, and bind its reviewed
hash. The repository copy at `server/skills/server-maintenance/` is the
canonical source and is registered under the same `$server-maintenance` name
as the user-level skill package; keep their `SKILL.md`, UI metadata, and
references synchronized. A Skill proposal does not grant backend authority.

## Safe implementation

1. Preserve the failing evidence and exact code revision.
2. For database changes, create and verify a backup before mutation; declare
   forward and rollback invariants.
3. Implement the smallest semantic fix in the owning module.
4. Run focused tests, then the affected server/client protocol and replay
   suites.
5. Measure database statements and bounded context/token costs on the hot path.
6. Obtain independent review; use grill-with-docs only for a method, graph,
   authority, migration, or scope change.
7. Record commit, test receipt, rollout target, and rollback target in the
   Maintenance Case.

Existing unaffected research jobs continue. Affected work pauses at its
capability gap and resumes only after the approved implementation and exact
compatibility checks pass.

## Infrastructure cases

Docker, WireGuard, and SSH operations are part of this contract only when the
Maintenance Case explicitly authorizes the target server and operation. Read
the private `server-maintenance` Skill's `references/infrastructure.md` before
changing a Compose project, tunnel identity, peer inventory, release checkout,
or public deployment. Keep client surfaces at 7998/7997 and keep peer surfaces
17998/17997 private to the FactorTester WireGuard overlay. PostgreSQL has its
own WireGuard identity and lifecycle; it is not an artifact transfer queue.

The public host does not fetch GitHub. An authorized publisher sends a clean,
exact `main` revision over the existing maintenance SSH transport, then uses
the native public release transaction to build, back up, activate, verify, and
retain a rollback target. A local `2222` forwarding or SSH transport setting
is an operator detail, never a public application port. Do not expose 22, 8000,
5432, 17998, or 17997 merely to make publication or federation work.

WireGuard public-key distribution belongs to the deployment coordinator and a
signed inventory, not to PostgreSQL, Manager settings, a container image, or a
client request. Private keys remain owner-only and never enter `.env`, Git,
logs, client bundles, or the Agent response. A Docker context may be used by
an authorized operator to administer a remote Docker daemon over SSH; it is not
FactorTester federation and must not be mounted into an application container.

## Confidentiality boundary

Client-visible responses may contain compact capability IDs, anomaly codes,
status, hashes, and bounded evidence references. They must never contain server
source, internal database paths, credentials, private factor definitions,
proprietary data, complete artifacts, or this maintenance procedure.
