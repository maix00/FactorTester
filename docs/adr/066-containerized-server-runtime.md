# ADR 066: Isolate server identity in a containerized runtime

## Status

Accepted.

## Context

A development Mac can simultaneously act as a FactorTester feature server and
run a native Swift client. Those actors must not share a WireGuard private key
or node identity. The feature server is also intermittent, owns multiple Git
worktrees, and must expose Manager 7998 and artifact 7997 to LAN clients without
publishing dynamic execution ports.

The public host has a different availability boundary: its WireGuard hub and
PostgreSQL control database must remain independently recoverable even when the
FactorTester application is being rebuilt or rolled back.

## Decision

1. A non-public FactorTester server is one Compose deployment with a
   WireGuard sidecar and a FactorTester Manager container. The sidecar alone
   mounts the server private key. The Manager shares its network namespace but
   cannot read the key. The sidecar may bring up multiple narrowly routed
   interfaces, such as one federation tunnel and one control-database tunnel;
   each interface has its own key and address.
2. Manager 7998, artifact 7997, and Manager-spawned test processes run in the
   shared network namespace. Compose publishes only 7998 and 7997. Dynamic
   ports remain bound to loopback and are reached through Manager as required
   by ADR 056.
3. Host port numbers are deployment parameters. A staging deployment maps
   `27998 -> 7998` and `27997 -> 7997`; federation continues to use the
   container's WireGuard address on invariant ports 7998 and 7997. Production
   cutover changes only the host mappings. Ports 17998/17997 are reserved for
   separate server-to-server transport work and are not defined by this ADR.
4. The Git common repository, Manager source worktree, read-only runtime
   `.settings` file, Manager state, and data root are bind-mounted at their
   original absolute paths. The settings file is mounted individually rather
   than exposing its parent directory. This preserves Git linked-worktree
   identity and data locality. The application image contains
   only the Linux runtime and dependencies; Python imports from the explicitly
   mounted source worktree so the running version is identified by its Git
   commit. The Docker socket is not mounted.
5. A configured WireGuard interface is a container liveness condition; a live
   peer handshake and PostgreSQL are not. WAN/control-database outages degrade
   affected requests but do not make the local Manager restart or disappear.
6. The Swift client receives a separate native key and address and does not
   join this Compose namespace.
7. The public host runs exactly two business containers. The
   `factortester-public` container owns one WireGuard identity and runs Manager
   7998, artifact 7997, and exactly one internal main-branch test service on
   fixed port 8000. It uses `server-role=main`, `fixed-port=8000`, and
   `fixed-branch=main`; it does not discover or start feature/issue worktrees.
   The `postgresql-control` container owns a second WireGuard identity,
   PostgreSQL process, data volume, and backup lifecycle. Each container
   configures its tunnel as root before dropping to its unprivileged
   application user; private-key files remain root-only inside that container.
8. The two public WireGuard identities use separate keys, tunnel subnets, and
   host UDP listeners (for example 51820 and 51821). Port 8000 is not published
   or opened in the security group, and public TCP 5432 remains closed.
   Same-host FactorTester-to-PostgreSQL traffic uses a non-published Docker
   network. Authorized remote server nodes reach PostgreSQL through its
   database-only tunnel. Swift clients never receive a database-tunnel peer.
9. Intranet container deployments consume a short-lived LAN-address snapshot
   produced in the host network namespace. They never retain a fixed host IP
   or advertise loopback, container bridge, or WireGuard addresses as LAN
   client targets. The dynamic lifecycle is specified by ADR-111.
10. Local feature/issue deployments may enable a source watcher that restarts
    only the Manager subprocess when mounted Python files change. Public
    `main` deployments prohibit hot reload and change code only through an
    explicit versioned deployment and process restart.
11. Federation TLS verification remains mandatory. A fingerprint-verified
    public Manager CA/certificate is mounted read-only into the application
    container; neither the application image nor deployment configuration
    disables certificate validation.

## Consequences

- Starting or stopping the local Compose project starts or stops its server
  tunnel identity together with FactorTester.
- LAN clients use the Mac LAN address and published 7998/7997 mappings, while
  peer servers use the container's WireGuard address.
- A compromised application process cannot directly read the WireGuard private
  key, although it can use the already-established network namespace.
- Docker Desktop must be running for the local server to be online; this is
  appropriate for an intermittent feature node and not for the public hub or
  PostgreSQL authority.
- The two public containers can update FactorTester without coupling it to a
  PostgreSQL restart or restore. Distinct WireGuard identities keep node
  authorization and revocation narrow without introducing two extra sidecars.
