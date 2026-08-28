# ADR 126: Profile Agents use filesystem isolation and retained assistance drafts

## Status

Accepted

## Context

A server-bound Profile Agent previously received a Profile-specific working
directory and Codex home, but ran as the same Unix user as other Profiles.  A
shell command could therefore read shared `/tmp`, sibling Profile directories,
or server storage by absolute path.  Page-assistance candidate JSON was also
written ad hoc into the Profile root or temporary storage.

## Decision

1. A server Profile Agent starts only inside a fail-closed Bubblewrap mount
   namespace.  Its Profile workspace is the sole writable mount at
   `/workspace`; `/tmp` is a private tmpfs; server user storage and sibling
   Profiles are not mounted.
2. The runtime, FactorTester CLI, Codex executable, certificates, and only the
   selected Skills are mounted read-only.  Network access remains available
   because the Agent must call its authenticated Manager and model provider.
3. Page-assistance candidates are created through the authenticated CLI/API and
   retained as flat JSON documents in
   `manifests/assistance-drafts/`.  The server assigns identity, page revision,
   content hash, status, and timestamps.
4. Drafts move through `draft`, `validated`, `applied`, or `rejected` states.
   Successful application does not delete a draft.  Quotas warn and eventually
   reject new drafts; they never silently delete retained documents.
5. The existing Profile workspace resource browser lists these documents and
   continues to use the 7997 object channel for downloads.  It gains explicit,
   owner-authorized regular-file deletion rather than introducing another file
   manager, authentication system, or storage protocol.
6. The live browser page remains the optimistic-lock authority.  A retained
   draft can be validated or applied only while its exact tab context is active
   at the recorded revision.

## Consequences

- Profile-relative current directories are no longer treated as a security
  boundary; absolute-path scans cannot reach sibling Profiles or shared temp.
- Agents use one structured draft protocol instead of inventing candidate file
  paths.
- Drafts remain user-visible and recoverable until the user explicitly deletes
  them, without adding a database table or a new settings tab.
- Deployments without Bubblewrap refuse to start server Profile Agents.
