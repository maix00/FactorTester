# Server and Client Release Plan

## Objective

FactorTester must become two independently releasable systems:

- the **server distribution** owns source code, data access, research
  computation, job scheduling, database migrations, backend maintenance Agents,
  and authoritative research semantics;
- the **client distribution** owns the remote HTTP client, local research
  workspace, approved local Skills, optional Vibe-Trading adapters, and the
  macOS application used to configure, install, update, and open those tools;
- the **local Agent workspace** owns the user's AI-Trader identity, research
  Agent identity, private research memory, and user-selected local profile.

An ordinary client user must neither receive nor import server implementation
code. A client can report a capability or backend-assurance gap, but only a
trusted server Agent with `server_backend_code` authority can inspect or change
the backend.

## Current-state evidence

The following observations are release blockers, not documentation gaps:

1. `maix00/FactorTester` is public and its default branch is `master`. Therefore
   repository access currently exposes server implementation even if client
   packaging is corrected.
2. Building `tools/cli` at `0.1.0` produces a 298-file, 2,487,981-byte wheel.
   It contains `tools/data`, `tools/factors`, the native backtest engine,
   exchange rules, server-oriented migrations, Harness tests, and other backend
   implementation. The packaging seam is not real.
3. `tools/cli/modules/custom_factors/controller.py` imports
   `tools.data.factor_research_registry`; the standalone client is not yet
   source-independent.
4. Harness provider locks and examples contain machine-specific
   `/Users/maxdeux/...` paths. Those are valid local discoveries, but invalid
   release defaults.
5. The 7998 manager hard-codes one local Vibe integration root and mixes
   developer worktree supervision with user application concerns.
6. The existing Swift macOS client configures a server and embeds server web
   pages, but it has no release manifest, dependency installer, updater,
   rollback, local research-workspace bootstrap, or Vibe lifecycle interface.
7. There is no root README, GitHub release workflow, release tag, or published
   GitHub release.
8. `/Users/maxdeux/Documents/Vibe-Trading-Integration/repos/Vibe-Trading` is on
   a Tiger-related local branch. It must not be used as a public fork source.
   `/Users/maxdeux/Documents/Agent Trader` also names local Tiger paths and is a
   private operator workspace, not publishable source.
9. The local Vibe integration already has an AI4Trade adapter and unified Agent
   gateway, but its defaults and operator README are MaxA-specific. They are
   evidence for a generic adapter, not release-ready client configuration.

## Required seams

### 1. Remote Research Protocol

This is the only seam shared by server and clients. Its interface consists of:

- authenticated HTTP endpoints and error contracts;
- version/capability negotiation;
- immutable ResearchWorkspace, RunSpec, ExecutionPlan, JobAttempt, artifact,
  Active Graph, and Backend Assurance references;
- bounded payload and polling/SSE behavior;
- explicit compatibility and upgrade errors.

The protocol schema and generated client models may be published. Server
implementations, database repositories, factor execution code, and maintenance
instructions may not cross this seam.

### 2. Client Distribution

The client distribution is a deep module with two adapters:

- `factortester`, a source-independent CLI;
- the macOS application, including a WebView adapter for existing research UI.

Both adapters use the same version manifest, authenticated session store, local
dependency inventory, and update transaction. No `server`, `tools.data`,
`tools.factors`, `tools.testers`, `sources`, or database module is permitted in
the client wheel or application bundle.

The Agent Harness is a separate optional client package. Its release catalog
contains capability descriptions and discovery hints, never developer absolute
paths or server-side Skill identity. Actual local Skill use remains in the
user's local research audit.

The distribution exposes one deterministic bootstrap interface, suitable for
direct use or for a coding Agent to invoke:

```text
factortester client bootstrap --profile <local-profile-file>
```

It creates a versioned client installation, a local factor-research workspace,
an Agent repository, and optional Vibe/AI-Trader adapters. It must be
idempotent, support `--dry-run`, and print a machine-readable plan before
mutation. It never accepts passwords or tokens on the command line.

The macOS application is a second adapter for the same bootstrap interface. Its
configuration form may ask for a local display name, AI-Trader registration
choice, FactorTester server URL, and workspace location. `MaxA` is an example
of a local display name only; it is neither a checked-in default nor release
metadata.

### 3. Server Maintenance

Server maintenance instructions live with the private server source and define:

- source-owner checks and repository authority;
- diagnosis, test, migration, rollout, rollback, and audit flow;
- the `BackendAssuranceGate -> backend_verifier -> CapabilityGap` route;
- the requirement that verifier and implementation Agents carry trusted
  `server_backend_code` authority and independent principal/lineage;
- database backup and migration invariants;
- token reservation and bounded evidence rules;
- the prohibition on exposing source, credentials, private paths, proprietary
  factors, or complete artifacts to a client or remote Skill.

Ordinary users can submit an anomaly receipt. They cannot launch a backend
verifier, create an implementation execution, approve code, or read server
source.

### 4. External Adapter Repositories

Vibe-Trading remains outside the server process. A publishable adapter fork must
start from a clean, pinned HKUDS upstream commit and contain only generic
FactorTester protocol adapters. Tiger paths, account identifiers, credentials,
broker tooling, local data, and proprietary research are excluded.

The local integration repository owns user-specific configuration and data
manifests. The macOS application installs or updates published adapters into a
versioned local dependency directory; it never overwrites local data or secret
configuration.

AI-Trader is also an optional client adapter. Registration or reuse happens
from the local bootstrap transaction:

- the user selects or creates their own AI-Trader identity;
- credentials/tokens are entered through the macOS UI or secure interactive
  prompt and stored in Keychain;
- the generated local research Agent receives only a credential reference and
  sanitized publishing policy;
- remote publication remains separately approved and excludes source code,
  local paths, private factor values, datasets, research memory, and broker
  information;
- reinstall reconstructs adapters from the local install/config receipt without
  re-registering an existing identity.

## Repository topology gate

Runtime packaging alone cannot satisfy source confidentiality while the current
server repository is public. Before the first production release, use one of
these equivalent secure topologies:

1. make the current FactorTester repository the private server repository and
   publish a new history-clean client repository; or
2. move server source and history into a new private repository, then replace
   the public FactorTester repository with a history-clean client repository.

The selected public client repository must have a single `main` branch. The
private server repository may retain its integration branches until server
rollout is proven. Remote branch deletion is the last operation, never a
prerequisite for testing.

## Implementation order and commit gates

Each numbered batch must be independently tested and committed before the next:

1. **Protocol and packaging gate**
   - add a server version/capability manifest endpoint;
   - make the CLI package contain only client code;
   - split the optional Harness package and exclude tests/local paths;
   - assert forbidden package prefixes and absolute private paths are absent
     from built wheels.
2. **Maintenance authority gate**
   - add server-maintenance Agent instructions;
   - distinguish client anomaly reporting from server code authority;
   - test that ordinary sessions cannot reach maintenance operations.
3. **Release manifest and updater gate**
   - define signed/checksummed release manifest and compatibility policy;
   - implement atomic client/dependency install, update, rollback, and status;
   - write only to versioned application support directories.
4. **macOS application gate**
   - show installed/latest/compatible versions;
   - configure the FactorTester server;
   - install/update CLI, Harness, research workspace, and approved adapters;
   - configure or reuse the user's own AI-Trader and research Agent identities;
   - start/stop/open local research UI without acquiring server authority.
5. **Vibe adapter gate**
   - compare the clean upstream baseline with required generic adaptations;
   - create a clean fork only if upstream cannot be consumed unchanged;
   - prove the fork contains no Tiger or local-private material.
   - expose the generic AI-Trader adapter without any MaxA defaults.
6. **Documentation gate**
   - replace the root README with server/client architecture, install, upgrade,
     recovery, privacy, database, and release instructions;
   - update client and server operator documentation.
7. **Clean-machine acceptance gate**
   - snapshot paths, checksums, versions, running jobs, and database identity;
   - back up the SQLite database and verify backup integrity;
   - remove only versioned application/client/dependency directories;
   - reinstall from the GitHub Release on this Mac;
   - reconnect to the preserved database and prove user/workspace/run/job
     identity, CLI login/logout, macOS UI, Vibe UI, and one bounded research job.
8. **Integration and release gate**
   - merge the decision-graph branch into issue-123;
   - run the issue-123 release gate;
   - merge issue-123 into `feat`, then `feat` into the stable branch;
   - migrate the stable branch name from `master` to `main`;
   - publish checksummed macOS and Python client artifacts from `main`.
9. **Remote cleanup gate**
   - download and reinstall the published release once more;
   - verify rollback and preserved database recovery;
   - verify the remote default branch is `main`;
   - only then delete every non-`main` remote branch explicitly requested by
     the owner. Local worktrees and databases are separate and are not deleted
     by this operation.

## Database and privacy invariants

- Never delete `Settings.CACHE_DB_PATH`, user-selected databases, local market
  data, retained research artifacts, Keychain items, or local research memory
  during a client reinstall.
- No cleanup command may derive its deletion root from an empty string, `/`,
  `$HOME`, `Documents`, or the repository parent.
- Every destructive acceptance step requires a generated inventory and a
  verified backup made before deletion.
- The clean reinstall test deletes only paths recorded in the client install
  receipt.
- Tiger-related paths and private identifiers are excluded by both a source
  scan and an artifact scan.
- User display names, including `MaxA`, AI-Trader identity, tokens, email,
  local workspace roots, and Agent memory exist only in the local configuration
  receipt or Keychain. Release fixtures use synthetic values.
- Release artifacts contain hashes and source revisions; update is atomic and
  rollback retains the previous version until post-install health checks pass.

## Token and database acceptance

- Routine version checks and local dependency status are deterministic and
  require zero LLM calls.
- The client loads Skill descriptions only when capability matching requires
  them, and loads Skill bodies only after explicit execution approval.
- Routine Active Graph context remains current-node-only and bounded.
- Server maintenance Agents start only for an explicit capability gap,
  backend anomaly, code proposal, or high-risk graph change.
- SQLite receives only low-frequency lifecycle, receipt, install, and audit
  facts. Download progress, process heartbeats, UI polling state, and update
  byte counters remain in memory or files.
- Release and clean-install tests measure wheel/app contents, request counts,
  database statement counts, and Agent/token counts rather than relying on
  architectural intent.

## Completion evidence

Completion requires all of the following authoritative evidence:

- forbidden-import and wheel/app-content tests;
- server authorization tests;
- signed manifest/update/rollback tests;
- macOS Release build and local UI walkthrough;
- clean install from the actual GitHub Release;
- database identity and row-count comparison before/after reinstall;
- Vibe adapter privacy scan and end-to-end connection;
- rewritten README rendered from `main`;
- GitHub default branch `main`, published release assets/checksums, and only the
  `main` remote branch remaining.

Until every item is proven, the overall migration remains incomplete.
