# ADR 105: Server-installed Skills for server Profiles

## Status

Accepted for the first server-side Agent Skill selection slice.

## Context

A server Agent may need FactorTester research instructions, but a user must not
upload arbitrary instructions or grant a server Agent Manager-maintenance
capabilities. The server also has to keep client-run Profiles separate: client
Skills are shipped and managed by the client application, not exposed by a
Manager's server catalog.

## Decisions

1. The deployed server owns an explicit Skill manifest at
   `server/manager/skills/catalog.json`. A Skill is available to a Profile only
   when it is listed, enabled, has a valid `SKILL.md`, and declares the matching
   runtime kind.
2. Only entries with `audience: profile` are shown to users. Manager-only
   maintenance Skills remain server-installed but are never returned by the
   Profile catalog route.
3. A user can only check or uncheck the server-provided Skill ids for a server
   Profile. The selection is stored in the Manager's existing local SQLite
   database. The Profile receives only owner-controlled symlinks under its
   canonical `.codex/skills` directory; Skill source files are not copied into
   a Profile or temporary Agent workspace and are not uploaded to PostgreSQL.
4. Browser responses contain Skill metadata and selection state, but never
   local filesystem paths. The server-side Agent supervisor obtains the
   selected installed bindings through `AgentProfileService.selected_skill_bindings`
   when it starts the claimed Profile Agent. It must construct the app-server
   Skill view from that allowlist and must not expose the repository-wide Skill
   directory.
5. The Profile app-server launch environment is isolated with its `.codex`
   directory as `CODEX_HOME`, `HOME`, and the XDG config/data/state roots.
   Before accepting turns, the supervisor must call `skills/list`, disable
   every discovered Skill outside the selected projection, re-enable selected
   Skills that were previously disabled, and refresh the list using
   `skills/config/write`. `turn/start` Skill inputs are constructed only from
   selected Skill ids.
6. The Manager now owns the server Profile app-server supervisor and exposes a
   narrow authenticated JSON-RPC/SSE bridge. It starts a process only after a
   Profile has an active claim and a valid local provider, keeps one process per
   Profile, and stops all child processes during Manager shutdown. Provider
   tokens are passed only through the child environment; they are not written
   to the Profile config file or returned by HTTP routes.
7. The browser may submit prompts and selected Skill ids, but cannot submit
   arbitrary Skill paths or arbitrary app-server methods. The supervisor
   forces the Profile workspace as `cwd`, validates `turn/start` Skill inputs,
   and redacts local paths and credential-shaped fields from responses/events.
   The browser bridge accepts text input only; image/file/mention inputs and
   per-request approval, sandbox, provider, capability-root, and permission
   overrides are rejected. Each generated Profile config fixes execution to
   `approval_policy = "never"`, `sandbox_mode = "workspace-write"`, and the
   Profile workspace with outbound network access. Codex's documented
   `shell_environment_policy.ignore_default_excludes = false` is also set so
   the provider token is removed from shell-tool environments even though the
   app-server itself receives it through its private child environment.
8. The first provider adapter is the OpenAI Responses-compatible wire
   contract. The existing Provider form remains the only API-key entry point;
   the API key is encrypted in Manager-local SQLite and is never returned by
   the list or connection-test routes. A connection test performs an
   authenticated, read-only `GET /models` request and verifies that the
   configured default model is present. The provider protocol field remains an
   extension seam for later adapters, but unsupported protocol values are
   rejected rather than treated as OpenAI.
9. A claimed server Profile Agent is started only after a local executable
   preflight for both Codex and the FactorTester CLI, followed by the provider
   health check. The FactorTester CLI path is supplied by `FACTORTESTER_CLI`
   or the installed `factortester` command and is added to the child process
   environment; a failed preflight prevents Codex from being spawned.

## Consequences

- Adding a research Skill is a server deployment/configuration change, not a
  user-facing upload operation.
- A server outage or SQLite failure prevents changing the selection, while an
  already running Agent can continue under the supervisor's existing process
  policy.
- Client Profiles keep their own app-managed Skill set and show no server Skill
  selection controls.
- An API-key or model outage is reported when the user tests the Provider and
  again before a new Agent process starts; no secret is included in either
  response. Future providers can add an adapter without changing Profile claim
  or workspace isolation semantics.
