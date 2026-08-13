# ADR 066: Federated transfer control and data plane

## Status

Accepted for staged implementation on 2026-08-13. This decision supersedes
ADR-065 and amends the cross-node portions of ADR-057.

## Context

An artifact is retained only on the server that executed its Job. Public
Managers can normally reach one another, while a feature server behind NAT can
make outbound connections but cannot accept an inbound connection from a
public Manager. ADR-065 made that private 7997 reachable through an SSH reverse
tunnel such as 17997. That works operationally, but makes SSH and one tunnel
port per node part of the application protocol.

A shared PostgreSQL-only transfer queue would remove the tunnel but would put
the control database in every cross-node download and upload. That contradicts
the required failure behavior: an already authenticated user must still be
able to transfer an existing file between online nodes while PostgreSQL is
temporarily unavailable.

Multiple public Managers add two independent ownership facts. The Manager
holding a private node's outbound control connection need not be the Manager
whose 7997 is serving the client. A durable request can move between Managers;
an active SSE connection or byte stream cannot.

## Decision

### Persistence authority

The Manager that receives the client request is the `request_owner`. It writes
the Transfer and its first outbox delivery intent atomically to its own
`transfers.sqlite`, using WAL. That local row is the authoritative request and
retry history. PostgreSQL stores only a rebuildable global index and audit
copy. PostgreSQL `LISTEN/NOTIFY` may wake a Manager but is never the durable
queue and is never required to start or resume a transfer.

Every cross-Manager command has a stable idempotency key. The request owner
retries its transactional outbox until a target Manager acknowledges the
command. Receiving Managers persist an inbox key before acknowledging it.
Audit events use a separate local outbox and are copied to PostgreSQL after it
recovers.

### Node control channel

A private node keeps one outbound SSE control connection to one healthy public
Manager per control domain. The SSE connection is a wake-up and command
channel, not the byte channel. A durable command sequence and `Last-Event-ID`
allow replay after reconnect; idempotent ACK requests and a bounded long-poll
endpoint are the fallback when SSE is unavailable.

The cluster registration credential is used only for first enrollment. The
node generates its own signing key, and subsequent challenge signatures bind
the connection to the stored node identity. A request parameter cannot select
the authenticated `server_id`. A node may only receive commands whose
`source_server_id` or `destination_server_id` is its authenticated identity.

### Transfer ownership and planning

Each Transfer Attempt fixes these identities before bytes move:

- `request_owner_manager_id`: authoritative SQLite and retry coordinator;
- `relay_owner_manager_id`: Manager whose 7997 meets producer and consumer;
- `connection_owner_manager_id`: Manager currently holding the commanded
  node's SSE connection;
- `source_server_id`, `destination_server_id`, and `storage_server_id`;
- one transfer mode and a hop budget of one.

The planner uses authenticated, expiring reachability observations rather than
hard-coded public/private roles:

1. same storage and relay node: local origin read or local staging write;
2. relay can reach the other node's 7997: direct pull or direct push;
3. source cannot be reached: source receives a command and actively pushes to
   relay 7997;
4. destination cannot be reached: destination receives a command and actively
   pulls from relay 7997;
5. no shared reachable relay: fail explicitly with node-unreachable status.

Public Managers normally use direct 7997 connections. A client always uses the
7997 of the Manager it selected; it is never redirected to a private node or
another node's loopback endpoint. The origin-side 7997 may only read or stage a
local file and cannot recursively select another federation route.

### Data plane

7998 carries metadata, commands, status, node presence, and short-lived
capabilities. Artifact and submission bytes use 7997 only. Producer, consumer,
and local-origin tickets are separate roles and bind transfer ID, attempt,
principal, nodes, expected size, expected SHA-256, permitted offset/range, and
expiry. Persistent stores keep ticket hashes, not bearer values.

A public relay does not persist file bytes. It meets one producer and one
consumer by transfer/attempt ID, applies bounded buffering and transport
backpressure, and times out an unmatched side. The execution or destination
node may write a private staging file, verify size and SHA-256, then atomically
promote it. A relay crash terminates the Attempt; the client resumes with a new
Attempt and a verified Range/offset. An in-flight socket is never claimed to
have failed over losslessly.

### PostgreSQL outage behavior

Local transfers, known-node cross-server transfers, existing sessions, local
identity caches, and outbox retries continue. New node enrollment and control
data mutations that need global authority pause. Global transfer indexing and
audit events remain in local outboxes and catch up asynchronously. A missing or
expired node presence record produces an explicit offline error instead of an
attempt to guess an endpoint.

### Module layout

The implementation uses semantic Modules rather than extending the existing
large federation, control database, job proxy, and artifact files:

```text
server/manager/
  transfers/
    models.py             # Transfer, Attempt, Command values
    state_machine.py      # valid state transitions
    planner.py            # reachability to fixed Attempt plan
    coordinator.py        # request-owner orchestration
    node_hub.py           # public Manager SSE ownership and replay
    node_agent.py         # private-node command execution
    security.py           # node and transfer capability verification
    presence.py           # authenticated expiring location observations
  storage/
    transfers/
      schema.py
      repository.py       # authoritative local requests and attempts
      outbox.py
      inbox.py
      tokens.py
      audit_spool.py
    control/
      ...                 # focused PostgreSQL Adapters, including audit
  data_plane/
    app.py                # sole 7997 process entry point
    routes.py
    origin.py
    relay.py
    streaming.py
    ranges.py
    integrity.py
  federation/
    registry.py
    gateway.py
    announcer.py
    sync.py
    transport.py
  http/
    jobs/artifacts.py
    jobs/submissions.py
    federation/node_control.py
    federation/transfers.py
```

`server.manager.app` remains the 7998 entry point. Once the new Modules own all
callers, the old implementations are deleted rather than retained as duplicate
compatibility paths.

## Transfer states

The durable request uses:

```text
created -> planned -> dispatched
                   -> waiting_producer / waiting_consumer
                   -> streaming -> verifying -> completed
                   -> retry_wait -> planned (new Attempt)
                   -> failed / expired / cancelled
```

Only declared transitions are accepted. Duplicate commands return the existing
record. A topology change always creates a new Attempt; a live Attempt never
switches from direct to push/pull halfway through.

## Migration and removal conditions

The cutover is staged while ADR-065 remains operational:

1. add the local repository, outbox/inbox, state machine, and characterization
   tests without changing live routing;
2. add node identity, presence, one SSE channel, ACK, replay, and long-poll;
3. implement local and directly reachable 7997 transfers;
4. implement source-initiated push and destination-initiated pull;
5. move Web, Swift, and CLI generated/submitted file paths to streaming 7997;
6. validate database outage, lost notification, SSE reconnect, relay crash,
   resume, integrity, authorization, and multi-public-Manager behavior;
7. stop advertising or generating 17997 URLs, remove the artifact reverse
   tunnel and its deployment settings, and remove the 7998 large-file fallback;
8. after all Manager control callbacks use the native node channel, remove
   17998 from normal operation as well. SSH remains an operations-only tool.

## Consequences

- PostgreSQL failure does not block an existing user's artifact transfer.
- A private node maintains one persistent outbound control connection instead
  of one connection per public Manager.
- Public Managers transfer directly where possible without involving SSH.
- Files retain a single durable owner; relay storage does not count against a
  second server or the user's distributed storage quota.
- Retry and resume are explicit Attempts, not hidden socket failover.
- The added semantics live behind focused Interfaces and do not further grow
  the current large Manager Modules.
