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
   database; Skill files are not copied into a Profile workspace and are not
   uploaded to PostgreSQL.
4. Browser responses contain Skill metadata and selection state, but never
   local filesystem paths. The server-side Agent supervisor obtains the
   selected installed bindings through `AgentProfileService.selected_skill_bindings`
   when it starts the claimed Profile Agent. It must construct the app-server
   Skill view from that allowlist and must not expose the repository-wide Skill
   directory.
5. The current slice provides the catalog, persistence, validation, and Profile
   UI. It does not itself start a Codex app-server process or implement its
   conversation transport; that supervisor remains a separate integration
   boundary.

## Consequences

- Adding a research Skill is a server deployment/configuration change, not a
  user-facing upload operation.
- A server outage or SQLite failure prevents changing the selection, while an
  already running Agent can continue under the supervisor's existing process
  policy.
- Client Profiles keep their own app-managed Skill set and show no server Skill
  selection controls.
