# FactorTester infrastructure maintenance

Load this reference only for an authorized Docker, WireGuard, SSH, or server
release case. It describes the boundary between operator transport,
FactorTester federation, client traffic, execution worktrees, and the control
database. It does not grant permission to change any of them.

## Contents

- [Topology and fixed surfaces](#topology-and-fixed-surfaces)
- [WireGuard membership and peer meaning](#wireguard-membership-and-peer-meaning)
- [Docker lifecycle](#docker-lifecycle)
- [CLI-Anything-compatible operator surface](#cli-anything-compatible-operator-surface)
- [SSH and public release](#ssh-and-public-release)
- [Failure and security boundaries](#failure-and-security-boundaries)

## Topology and fixed surfaces

The public web and Swift clients use only the stable client surfaces:

| Surface | Port | Network | Owner | Rule |
|---|---:|---|---|---|
| client control | TCP 7998 | public or LAN ingress | Manager | UI, sessions, metadata, scheduling, short-lived transfer access |
| client data | TCP 7997 | public or LAN ingress | Manager data plane | capability-authorized upload/download bytes |
| peer control | TCP 17998 | FactorTester WireGuard only | Manager peer plane | node registration, discovery, tickets, service forwarding |
| peer data | TCP 17997 | FactorTester WireGuard only | Manager peer plane | origin reads and destination writes |

Execution services such as the local `feat` service on 7999, the public
`main` service behind internal 8000, and issue-worktree ports such as 8141 are
owned by their Manager and remain loopback services. They are never published
as client or peer ports. A task is routed through the owning Manager rather
than by opening an execution port on the host.

The public deployment normally has two business containers:

1. `factortester-public`, which contains the public Manager/runtime and its
   FactorTester WireGuard identity/interface;
2. `postgresql-control`, which contains PostgreSQL and its independent
   database WireGuard identity/interface.

The local deployment uses a WireGuard container with the Manager sharing its
network namespace. This is still one FactorTester node: the WireGuard sidecar
owns the tunnel and published 7998/7997 mappings, while Manager owns the
application listeners. Do not infer node identity from the number of Docker
containers.

FactorTester and PostgreSQL tunnels have separate identities and lifecycles.
The public host may accept UDP 51820 for the FactorTester tunnel and
UDP 51821 for the database tunnel. PostgreSQL TCP 5432 is private to the Docker
network or database WireGuard path and is not a public security-group
surface. The same applies to 8000, 17998, and 17997. Do not add an inbound
rule for a port merely because a container listens on it internally.

## WireGuard membership and peer meaning

WireGuard authenticates configured public keys and routes configured
`AllowedIPs`; it does not discover peers or distribute keys. Keep these
responsibilities separate:

- Each deployment generates and retains its own private key with owner-only
  permissions. Only its public key leaves that deployment.
- A deployment coordinator owns the versioned, signed public inventory. The
  inventory records `server_id`, tunnel kind (`factortester` or `database`),
  overlay address, endpoint, routes, generation, and enabled/revoked state.
- Manager, PostgreSQL, Git, a client setting, and a container image do not own
  the inventory signing secret and do not mutate WireGuard membership.
- FactorTester and PostgreSQL keys rotate independently. Stage the new key,
  verify the handshake and private health endpoint, then revoke the old public
  record before removing the old local material.

`bootstrap_url` is one seed for application discovery, not a permanent
singular peer. A directory may contain many nodes. Discovery is not
authentication: activate a direct authenticated relation only when a task,
data source, artifact, submission, or execution port actually selects that
node. Do not create one listener or one long-lived request channel per public
server.

Public nodes can use direct WireGuard paths. A private/NAT node can use one
approved public gateway for encrypted IP forwarding, with optional standby
metadata. The application still addresses the selected node's 17998/17997
overlay endpoint. The gateway forwards packets only; it does not proxy,
persist, mirror, or receive artifact bytes at the application layer.

The checked-in inventory helper is:

```bash
python scripts/server/factortester_wireguard_inventory.py --help
python scripts/server/factortester_wireguard_inventory.py generate-node-key --output-dir <owner-only-dir>
python scripts/server/factortester_wireguard_inventory.py verify \
  --inventory <signed-inventory> --trusted-public-key <inventory-public-key>
```

Use `generate-signing-key`, `sign`, and `render` only in the authorized
deployment-coordinator workflow. Never place the resulting private key,
registration bearer, database password, or Manager session in Git, `.env`, a
client bundle, a log, or a response. Validate file ownership and modes before
applying a rendered configuration.

## Docker lifecycle

Use the repository's native wrappers and discover their current options with
`--help`; do not stop ports or containers by PID:

```bash
scripts/server/factortester_container.sh config
scripts/server/factortester_container.sh status
scripts/server/factortester_container.sh port
scripts/server/factortester_container.sh up
scripts/server/factortester_public_container.sh status
scripts/server/factortester_public_container.sh verify
```

The local `up` and public `up` operations reconcile from existing images and
must not build or pull implicitly. Build explicitly after a Dockerfile,
dependency lock, or pinned runtime change. Source-only local feature changes
use the mounted, explicit worktree and the Manager's approved hot-reload or
restart transaction. Public `main` uses a clean full SHA, an immutable
SHA-tagged image, and hot reload disabled.

Separate server IDs, settings, state roots, data roots, runtime roots, and
WireGuard identities are mandatory. Do not point two nodes at one SQLite or
state directory, and do not mount the broad repository parent or Docker socket
into the application. The application image supplies the runtime and pinned
dependencies; a release checkout supplies the explicitly selected source.

Use `restart-fleet` for a local Manager-owned service set so the current set
is captured, drained, restarted, authenticated, and restored as one
transaction. A single execution port such as 8141 may be targeted only by the
existing per-port option and only with explicit authorization for a force
stop. A Docker restart is not a substitute for the Manager transaction when
the change is in a running worktree.

Never use `docker system prune`, delete named PostgreSQL volumes, or remove a
release image/worktree outside the retention operation. Public cleanup keeps
the newest verified releases and leaves the active release and database
volume untouched. `down` is an explicit stop and must not imply data loss.

## CLI-Anything-compatible operator surface

The maintenance interface is CLI-first and wraps the real Docker, Git, SSH,
and FactorTester backends. It is not a second implementation of those
backends, and it does not require a GUI or an interactive REPL for a release or
restart transaction.

- Discover the current command contract with the native `--help` surface
  before invoking a mutating operation. Use one-shot subcommands that can be
  composed in an unattended release or incident workflow.
- Prefer `--json` for the Manager transaction and other native machine-readable
  commands. Treat human log text as diagnostic output, not as an API. For
  shell wrappers, check their exit status and validate the resulting Docker,
  revision, identity, and port state.
- Exercise the real backend in validation: run wrapper `--help`, shell syntax,
  non-mutating Compose config/status/port checks, Manager help, and a public
  `verify` against an authorized deployment or isolated fixture. Do not declare
  success from process exit alone when a revision, port, key, backup, or health
  invariant can be checked.
- Keep mutations explicit (`build`, `up`, `restart`, `publish`, `down`) and
  never hide a build, pull, prune, Git fetch, or volume deletion inside a
  status/help operation. A deployment failure must return a non-zero status
  and leave the last verified release or captured Manager set recoverable.

Do not create a duplicate `cli-anything-factortester-server` harness merely to
wrap these existing operational commands. The native FactorTester CLI and
server wrappers already provide the stable backend surface; this Skill adds
the decision rules, routing, and verification contract around them.

## SSH and public release

SSH is operator maintenance transport, not FactorTester federation and not an
artifact path. A Docker context may let an authorized operator inspect or
restart a remote Docker daemon over SSH; it does not make remote containers
part of the local FactorTester node and must never be mounted into an app
container.

The public server must not fetch GitHub. The authorized local publisher runs
from a clean `main` checkout and sends missing Git objects directly to the
public bare repository over the existing maintenance transport. The transport
may be an SSH alias, a local `2222` forwarding port, or an approved Alibaba
Session Manager route, depending on deployment configuration. `2222` is a
local operator-side convention, not a public service port; do not assume the
remote host exposes TCP 22.

The native release sequence is:

1. validate that local `main` is clean and record the full 40-character SHA;
2. transfer the missing objects and verify the remote bare-ref SHA;
3. create or reuse the detached release checkout for that exact SHA;
4. build the versioned application image explicitly;
5. back up PostgreSQL and preserve the current application/database identity;
6. switch the application environment and restart only the application;
7. verify revision, client ports, private database access, distinct WG keys,
   no accidental 8000/5432/17998/17997 publication, and the restore check;
8. append a verified deployment record and remove only old releases outside
   the retention set.

If activation or verification fails, restore the previous environment and
application image. Keep PostgreSQL's named volume and its external dump. The
public host should never silently fetch a different branch or build from an
unclean checkout. A failed publication must leave the last verified release
running.

## Failure and security boundaries

- A WireGuard container being healthy proves that the interface process is
  running, not that the selected peer has a current handshake. Check the
  overlay route and private health endpoint separately.
- Missing or expired peer metadata yields the Manager's explicit
  `node_unreachable` policy. Never fall back to a public 7998 URL, guessed
  execution port, SSH tunnel, or application-layer relay.
- A PostgreSQL outage must not stop an already-authorized Manager or turn
  PostgreSQL into a byte-transfer queue. Queue only the approved local audit or
  projection work for later recovery.
- Client cookies and Manager sessions do not cross into 7997 data requests.
  Peer tickets are short-lived, role-scoped, bound to node/request/attempt and
  stored as hashes where persisted.
- Do not print private keys, bearer values, database URLs, source paths,
  proprietary data, or complete artifacts in maintenance output.
- Stop before mutation when the target server, revision, identity, backup,
  rollback target, or authorization is ambiguous.

For the normative protocol decisions, read `docs/adr/068-wireguard-direct-
transfer-surfaces.md` and `docs/adr/070-federation-bootstrap-and-wireguard-
key-governance.md`, then the relevant deployment README. Do not copy those
documents or this private reference into a public client or generated Agent
packet.
