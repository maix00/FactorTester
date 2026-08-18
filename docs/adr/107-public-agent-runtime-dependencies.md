# ADR-107: Public Agent runtime dependencies

## Status

Accepted

## Context

The public Manager hosts server-side Profiles. A Profile's app-server must be
able to start the Codex `app-server` protocol and invoke the user-facing
FactorTester research CLI. The Manager/operator CLI belongs to server
administration and must not be part of the Agent command surface.

The public image is built and activated from an exact Git revision. Runtime
dependencies therefore need to be installed and checked during the image
build, without storing provider tokens or the private Mihomo subscription in
the repository.

## Decision

- Install a pinned `@openai/codex` npm release in the public image and verify
  `codex --version` during the build.
- Install the `tools/cli` Python distribution into the image so the
  `factortester` launcher resolves through the installed bootstrap rather than
  a checkout on the Agent's working directory.
- Remove the `factortester-manager` launcher after installation. Its Python
  modules remain part of the Manager application source, but the ordinary
  Agent PATH does not expose its command.
- Keep the Codex npm registry and version as Compose build arguments. Keep
  provider credentials and Mihomo subscription configuration runtime-only.

## Consequences

The public image is larger because it contains Node.js and the Codex Linux
runtime, but Profile app-server startup is deterministic and does not depend
on a host installation. Updating Codex is an explicit image revision and is
covered by the normal build, publish, restart, and verification transaction.
