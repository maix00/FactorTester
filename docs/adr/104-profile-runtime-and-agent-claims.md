# ADR 104: Profile runtime ownership and Agent claims

## Status

Accepted for the first server-side Agent/Profile management slice.

## Context

FactorTester has two execution environments: the local client and a Manager
server. A research Profile is a durable identity and must not silently become
several temporary Agent workspaces. Model-provider credentials also belong to
the runtime that uses them and must not enter PostgreSQL, browser projections,
or Profile metadata.

## Decisions

1. A Profile has one canonical workspace and at most one durable Agent binding.
   Heartbeats describe whether the bound Agent is currently online; they are
   not ownership leases and never release or replace a binding. Only an
   explicit release, an authorized administrative release, or Profile deletion
   removes the binding. Multiple Profiles may bind the same `agent_id`; their
   workspaces, conversations, permissions and runtime states remain scoped by
   `principal + profile_id`.
2. Every runtime is explicit: `client` is bound to one client device and
   `server` is bound to one Manager `server_id`. A server Profile cannot be
   claimed by a different Manager. The UI exposes both runtime kinds in the
   Research / 研究身份 tab.
3. Client and server use the same portable relative layout:

   ```text
   users/<principal>/profiles/<profile-id>/
   ├── factor-worktree/
   ├── strategy-worktree/
   ├── research/
   ├── reports/
   └── manifests/
   ```

   The client root is `Documents/FactorTester`; the Manager root is its
   configured data root. No `agent-temp`, `agent-sessions`, scratch copy, or
   data-source mount is created.
4. An Agent obtains data through the existing Manager control/data surfaces
   (7998/7997) and the FactorTester CLI. The Agent does not receive a mounted
   server data-source directory.
5. Model connections are managed in the separate Research / 智能体模型 tab.
   Provider records are Manager-local SQLite rows with an encrypted token and
   an owner-only key file. API responses expose metadata and a boolean token
   flag, never the token. Server-runtime providers require HTTPS; client
   runtime credentials are written by the local client, not by a public
   Manager.
6. The existing Research module is the only navigation owner. No new Agent
   homepage module is added. The existing Profile projection is enriched with
   runtime and active-claim metadata, while secrets remain outside it.

## Consequences

- The Manager can coordinate ownership and display a Profile's runtime without
  running a resident research Agent or deciding the next research-graph edge.
- A server restart, stopped Agent process, missed heartbeat, browser closure or
  page eviction preserves runtime bindings in the Manager's existing SQLite
  database. A disconnected binding continues to block implicit replacement
  until it is explicitly released.
- On upgrade, the newest legacy row marked `expired` is restored as a stopped
  binding only when that Profile has no current binding. Rows marked by an
  explicit `released` operation are never restored.
- A real Agent runner still has to use these APIs and the canonical workspace;
  this ADR does not authorize an additional temporary execution directory.
