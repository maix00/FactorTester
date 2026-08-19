# ADR 114: Public Manager Codex sandbox inside Docker

## Status

Accepted for the public Manager Agent runtime.

## Context

The public Manager starts one Codex `app-server` per claimed research
Profile. Codex's Linux `workspace-write` policy uses bubblewrap with user and
PID namespaces. The public container previously installed bubblewrap as an
ordinary executable and also enabled Docker's `no-new-privileges` option. On
the Alibaba Cloud host this caused every Agent command to stop at:

```text
bwrap: No permissions to create new namespace
```

The Manager and PostgreSQL containers are separate services. The Manager
mounts application state and control-plane secrets, so enabling unrestricted
execution for the whole container would make a model prompt or workspace
payload a broader host-facing risk.

## Decision

The public FactorTester service uses the official Codex secure-container
pattern:

1. Install the distribution bubblewrap package and set `/usr/bin/bwrap` to
   setuid mode during image construction.
2. Give only the FactorTester service the explicit capabilities required by
   that pattern (`SYS_ADMIN`, `SYS_CHROOT`, `SETUID`, `SETGID`, `SYS_PTRACE`,
   `NET_ADMIN`, and `NET_RAW`).
3. disable Docker's outer default seccomp and AppArmor profiles for that
   service so bubblewrap can create its inner sandbox.
4. Do not set `privileged: true`, do not grant these capabilities to
   PostgreSQL, and keep PostgreSQL under `no-new-privileges`.
5. Keep Codex's own `workspace-write` policy and in-process seccomp/
   `no-new-privs` enforcement unchanged. The outer relaxation exists only to
   construct the inner sandbox; it is not a request for Agent full-disk
   access.

No FactorTester transport port is added. The existing public `7998`, `7997`,
and WireGuard UDP port remain the only published application ports.

## Why this choice

The official Codex secure Docker profile documents this exact boundary. A
temporary container using the deployed public image and this profile passed
`codex sandbox -- /bin/true` on the target host. The target kernel rejects the
fresh `/proc` mount used by bubblewrap, but the current Codex sandbox helper
preflights that mount and retries without it; no unrestricted fallback is
enabled.

Setting `sandbox_mode = "danger-full-access"` or `privileged: true` in the
Manager would make the Agent work by removing the relevant security boundary,
so neither is an accepted fix.

## Consequences

- The public image must preserve the setuid bit on `/usr/bin/bwrap`.
- Docker/AppArmor policy changes are explicit and limited to the Manager
  container; the PostgreSQL container remains hardened separately.
- A host that rejects the required Docker capabilities or setuid execution
  will fail the Agent sandbox smoke test rather than silently running without
  isolation.
- Rolling back the public image and Compose revision restores the previous
  hardened container, but Agent shell commands will again be unavailable on
  this host until the sandbox prerequisites are restored.

## References

- OpenAI Codex secure container profile:
  <https://github.com/openai/codex/blob/main/.devcontainer/README.md>
- OpenAI Codex Linux sandbox behavior:
  <https://github.com/openai/codex/blob/main/codex-rs/linux-sandbox/README.md>
