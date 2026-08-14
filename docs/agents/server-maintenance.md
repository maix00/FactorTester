# Server Maintenance Agent Contract

## Separate local development from server operations

There are three different activities and they must not be collapsed into one
login requirement:

| Activity | What it covers | Required authority |
|---|---|---|
| Local repository work | Inspecting, editing, testing, and committing source in the current checkout | The user's repository task authorization and normal local tooling |
| FactorTester runtime maintenance | Protected Manager actions, bounded maintenance cases, server-side migrations, or production-like validation | An authenticated developer and the server-issued `server_maintenance`, `backend_verifier`, `implementation_agent`, or `server_backend_code` authority as applicable |
| Release/deployment | Merge/push, transfer to the public host, remote reload, rollback, Docker/WireGuard/SSH operations | Explicit release authorization plus the separate remote administrator/Aliyun transport credential |

Private backend code under the local checkout is not, by itself, a reason to
stop local source work or demand a remote maintenance role. The protected
server roles apply when the agent invokes the server's runtime authorization
or mutates a deployed environment. Git merge/push and public deployment are
separate approvals even when the source change is already committed.

The CLI's local Manager credential is URL-scoped and stored in macOS Keychain
under `com.gtht.factortester.manager`; use `factortester manager status` to
inspect the authenticated Manager principal without exposing the bearer value.
That token is not the ordinary FactorTester browser/CLI session cookie used by
`resume.py`, and it is not an Aliyun SSH credential. A `401` from the bounded
FactorTester resume endpoint therefore does not prove that no Manager
administrator is available locally.

## Entry conditions for runtime maintenance

Start the runtime-maintenance flow only for a concrete backend anomaly,
unresolved capability gap, approved backend change, migration, or high-risk
graph change. A passing Backend Assurance Gate is the deterministic fast path:
continue research without a verifier or LLM review.

The authenticated account must be a developer for this flow. The server, not
the client, authorizes `server_maintenance`, `backend_verifier`,
`implementation_agent`, and `server_backend_code`. Ordinary sessions may
submit bounded anomaly evidence but cannot claim these roles. Do not request
this packet merely to edit or test local source.

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
hash. A Skill proposal does not grant backend authority.

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

## Confidentiality boundary

Client-visible responses may contain compact capability IDs, anomaly codes,
status, hashes, and bounded evidence references. They must never contain server
source, internal database paths, credentials, private factor definitions,
proprietary data, complete artifacts, or this maintenance procedure.
