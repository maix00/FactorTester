# FactorTester

FactorTester is a remote factor-research service with a separately releasable
client. The server owns data, execution, research jobs, database migrations,
and authoritative research semantics. Public clients receive only the HTTP
protocol adapter, optional Agent Harness, signed local adapters, and the macOS
application.

## Architecture

```text
local factor workspace / Agent
              |
      FactorTester CLI + Harness
              |
      authenticated HTTP protocol
              |
       private FactorTester server
              |
     jobs, data, artifacts, database
```

The client never imports server execution code. A client may report a
capability or backend-assurance gap, but only an authorized
`factortester-server-maintenance` Agent can inspect or modify backend code.

## Client

The public client release contains:

- the source-independent `factortester` CLI;
- the optional `cli-anything-factortester-research` Harness;
- the macOS SwiftUI application, including embedded server and local-adapter
  Web views;
- signed local adapter archives, initially Vibe-Trading;
- pinned Python dependency wheels for offline materialization.

See [Client installation and recovery](docs/client-release.md) and
[macOS client](apple/README.md).

## Server

Server deployment and maintenance instructions are private operational
material. Maintainers must follow
[FactorTester server maintenance authority](docs/agents/factortester-server-maintenance.md), including
authorization, bounded evidence, database backup, migration, and rollback
requirements.

## Privacy and persistence

A client reinstall changes only versioned paths recorded in its release
receipt. It does not delete or upload:

- server or user-selected databases;
- market data and research artifacts;
- factor source, formulas, or expression trees;
- Keychain credentials;
- local research memory or workspaces.

Jobs and factor-library metadata may remain on the server without retaining
factor source. Source synchronization occurs only when enabled by the user.

## Development and release

The signed release manifest binds every artifact to its byte size, SHA-256
digest, source revision, protocol range, and trusted ECDSA key. Installation is
staged, health-checked, and atomically selected; rollback changes only the
version pointer.

Release protocol and acceptance details are in
[the server/client release plan](docs/server-client-release-plan.md). A release
is not complete until its downloaded GitHub artifacts pass clean installation,
rollback, database-preservation, CLI authentication, macOS UI, adapter UI, and
bounded research-job checks.
