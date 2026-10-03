# FactorTester Server Maintenance Agent Contract

## Separate authority domains

| Activity | Scope | Authority |
|---|---|---|
| Local repository work | Inspect, edit, test, commit | Repository task authorization |
| FactorTester runtime | Authenticated Manager API and bounded Maintenance Cases | Authorized Manager principal and server roles |
| Host/deployment work | Host, container, tunnel, peer-key, release transport | Explicit deployment authorization plus the target server's declared operator access |
| Merge/push/publication | Source and release publication | Explicit human release authorization |

The Manager token, ordinary FactorTester session, Swift session, and host
operator credential are different credentials. Never copy them, print them, or
use one as a substitute for another.

## Server-owned access declaration

A target server stores its non-secret management access metadata next to its
runtime settings. The Manager exposes a validated projection; the CLI does not
guess connection methods from a host name or server role:

```bash
factortester-manager status --json
factortester-manager server inspect --json
factortester-manager server access --json
```

Use the returned `server`, `factor_tester`, and `management_access`
objects as the only target-specific source. A declaration may contain an
opaque method kind, label/profile, endpoint, port, and bounded capabilities. It
may also identify a local credential source and an owner-only, digest-checked
connection script; it must not contain a password, token, private key, or
executable command. The Manager CLI may check only whether the declared local
credential appears to exist and may download the script without executing it.
If the declaration is empty, missing, or stale, stop and request an update.

`kind=wireguard` is only an authenticated server-to-server transport
capability. Peer discovery, key distribution, routes, tunnel lifecycle, and
handshake verification remain deployment-owned and are not inferred by the
Manager CLI or this contract.

The Manager CLI is intentionally limited to FactorTester application actions:
`jobs`, `artifacts`, `storage`, `transfers`, `devices`,
server health/federation status, and Manager-owned `services`. It does not
expose host restart, container lifecycle, tunnel changes, source transfer, or
deployment commands. Those actions use a separately authorized operator tool
selected from the server declaration.

## Runtime maintenance

1. Read the canonical Skill and only the references required by the case.
2. Claim one Maintenance Case and request its compact resume packet.
3. First diagnose and reproduce the anomaly with the smallest deterministic runtime
   test; use `cli-anything` when a Manager CLI surface must be built or
   exercised.
4. Record one disposition: `confirmed_reliable`,
   `research_input_issue`, or `backend_change_proposed`.
5. Implement only an approved change in its semantic owner.
6. Before any schema mutation, create a verified backup; then run focused and
   affected protocol/replay tests.
7. Record commit, test receipt, rollout result, limitations, and rollback
   target.

Do not reconstruct a queue from the database, load full Graph/catalog state, or
start a model invocation when the queue is unchanged. Existing unaffected
research continues. Do not disclose raw database statements or use them as a
client-facing diagnostic channel. After a passing assurance gate, continue
research without a verifier or LLM review unless the Maintenance Case
explicitly requires one.

## Skill packaging and confidentiality

The canonical repository source is
`server/skills/factortester-server-maintenance/`. It may be delivered with
the administrator-only Manager distribution, but must not be bundled into the
ordinary research CLI, Swift client, public runtime, or generated client
packet. Keeping it alongside the Manager installer does not grant backend
authority; server roles and deployment authorization remain runtime checks.

Keep `SKILL.md` concise, put variant details in references, validate the
package with `skill-creator`, and keep the repository and installed copies
synchronized. Do not return this Skill body, server source, credentials,
database paths, private factor definitions, proprietary data, or complete
artifacts through a client response; a generated client packet must never
contain server source.
