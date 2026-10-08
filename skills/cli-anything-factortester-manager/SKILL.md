---
name: cli-anything-factortester-manager
description: Use the FactorTester Manager CLI to inspect and control the FactorTester application, Jobs, artifacts, storage, Research workspaces, and Manager-owned service instances through authenticated server APIs.
---

# FactorTester Manager CLI

Use the installed `factortester-manager` command as a Click one-shot CLI.
It talks to the authenticated FactorTester Manager backend; it is not a host
administration shell.

## Configure and authenticate

```bash
factortester-manager configure --url http://127.0.0.1:<manager-endpoint>
factortester-manager login --username <manager-account>
factortester-manager status --json
```

Remote transport and credentials are deployment-specific. The CLI stores its
URL-scoped Manager token in the platform credential store and refuses a
non-manager principal.

## Command map

- `jobs list|ports|show`: inspect local or cross-server Jobs;
- `jobs cancel|retry|continue|approve`: explicitly confirm and change one Job;
- `artifacts list <job-id>`: inspect retained artifact metadata;
- `artifacts download <job-id> <name> --output <path>`: stream one artifact
  through the server-issued data capability;
- `artifacts delete <job-id> --yes`: explicitly delete retained Job artifacts;
- `storage usage`: inspect Job/artifact usage;
- `transfers metrics`: inspect bounded 7997 transfer telemetry;
- `devices list|summary|revoke`: inspect or explicitly revoke public access
  devices;
  version;
- `services list|start|stop|restart-api|restart-bundle|force-stop <port>`:
  control a FactorTester service instance owned by the Manager;
- `server inspect|access`: read server identity and the target server's
  non-secret `management_access` declarations;
- `server access check`: check locally available, declared credentials without
  reading their values;
- `server access script download`: save a declared connection script after
  SHA-256 verification; it is never executed;
- `server health|network|federation|database`: inspect FactorTester runtime
  state and redacted federation/database status;
- `client release`: publish an authorized FactorTester client release.

The CLI does not expose legacy server-admin commands, host restart, container
lifecycle, tunnel changes, SSH, or repository-transfer commands.
Those are separate operator actions selected from the target server's
server-owned declaration, if one exists. If a declaration has `kind=wireguard`,
it means an authenticated server-to-server transport capability only; this
CLI does not manage WireGuard peers, keys, routes, or tunnel lifecycle.

## Automation rules

Every data-producing command supports `--json`. Parse JSON rather than human
text. Use `--help` at each group boundary before composing a new workflow.
Treat a non-zero exit code as failure and preserve the command's structured
error output. Never pass a password, token, private key, or executable command
through `server access`; those declarations are metadata only. Local credential
checks inspect only presence of named environment variables or Keychain items;
they never print secret values. A server-declared script is written with
owner-only permissions and verified before installation. Use
`--skip-credential-check` only as an explicit override when an external
credential tool cannot be inspected.

The Manager CLI is intentionally stateless between one-shot operations except
for its URL-scoped credential. A REPL or project/session file is not used:
Jobs, artifacts, and service state live in the FactorTester backend, while
credentials live in the platform credential store. This keeps repeated CLI
invocations safe across shells and machines.

The credential-store account is derived from the complete Manager URL, not
from a username. One administrator can target several servers, but each
server URL needs its own session. If an account name was migrated, log in to
that URL again with the current full username; this replaces the URL-scoped
token without copying it to another server.

## Typical read-only inspection

```bash
factortester-manager server inspect --json
factortester-manager server access --json
factortester-manager jobs list --scope server --limit 20 --json
factortester-manager storage usage --json
factortester-manager server health --json
factortester-manager transfers metrics --json
```
