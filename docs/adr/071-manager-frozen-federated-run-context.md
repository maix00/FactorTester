# ADR 071: Manager-frozen context for federated Run submission

## Status

Accepted for Issue #185 on 2026-08-13.

## Context

Research workspaces and their editable configurations are authoring state owned
by the Manager that the user is currently using.  Execution services may run
on another server and do not share that Manager's SQLite files.  Forwarding
only `workspace_id` and `configuration_revision` therefore makes a remote
service fail before it can evaluate data-source capability.  Replicating the
editable workspace database would also introduce conflict resolution into the
task-submission critical path.

## Decision

The origin Manager freezes a Run request once, before route selection.  It
resolves the owner-scoped workspace, configuration or snapshot, product
selections, factor revisions, source manifests, analysis options and optional
Profile identity into the same immutable prepared request used by the local
execution API.

The Manager adds that prepared request under the reserved
`_manager_run_context` field.  The envelope contains:

- a schema version;
- the authenticated owner;
- the canonical RunSpec hash;
- the validated and frozen prepared request.

The exact same envelope is sent to every candidate's read-only capability
preview and to the selected service's Run submission.  An execution service
validates the owner, schema, configuration fingerprint, RunSpec relationships
and RunSpec hash, then executes without reading its own workspace database.

Client values under the reserved field are always removed and replaced by the
origin Manager.  Peer transport remains authenticated on WireGuard port 17998;
execution ports remain loopback-only and accept the context only through their
local Manager capability.  The envelope has a bounded encoded size so Base64
federation framing remains below the private control endpoint's request limit.

This is a snapshot transfer, not workspace synchronization.  Subsequent edits
on the origin create a different context and RunSpec.  PostgreSQL does not
store or broker the request and is not added to task submission's critical
path.

## Consequences

- A server can execute a Run for an origin-owned workspace without copying the
  workspace SQLite database.
- Capability selection evaluates the exact configuration that is eventually
  submitted, eliminating an edit/preflight race.
- Built-in or uploaded source compatibility is still checked by the candidate
  executor; an unavailable factor or data source remains an explicit error.
- Large user files continue to belong on the 7997/17997 data plane.  The
  control envelope is suitable only for the already-bounded Run authoring
  request and its source metadata or small inline source bundles.
