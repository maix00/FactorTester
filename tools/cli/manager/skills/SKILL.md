---
name: cli-anything-factortester-manager
description: Use the FactorTester Manager CLI to inspect and control the FactorTester application, Jobs, artifacts, storage, Research Graph versions, and Manager-owned service instances through authenticated server APIs.
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

- `jobs list` and `jobs ports`: inspect local or cross-server Jobs;
- `artifacts list <job-id>`: inspect retained artifact metadata;
- `artifacts download <job-id> <name> --output <path>`: stream one artifact
  through the server-issued data capability;
- `storage usage`: inspect Job/artifact usage;
- `research-graph versions|active|set-default`: inspect or activate a graph
  version;
- `services list|start|stop|restart-api|restart-bundle|force-stop <port>`:
  control a FactorTester service instance owned by the Manager;
- `server inspect|access`: read server identity and the target server's
  non-secret `management_access` declarations;
- `client release`: publish an authorized FactorTester client release.

The CLI does not expose legacy server-admin commands, host restart, container
lifecycle, tunnel changes, SSH, or repository-transfer commands.
Those are separate operator actions selected from the target server's
server-owned declaration, if one exists.

## Automation rules

Every data-producing command supports `--json). Parse JSON rather than human
text. Use `--help` at each group boundary before composing a new workflow.
Treat a non-zero exit code as failure and preserve the command's structured
error output. Never pass a password, token, private key, or executable command
through `server access`; those declarations are metadata only.

The Manager CLI is intentionally stateless between one-shot operations except
for its URL-scoped credential. A REPL or project/session file is not used:
Jobs, artifacts, and service state live in the FactorTester backend, while
credentials live in the platform credential store. This keeps repeated CLI
invocations safe across shells and machines.

## Typical read-only inspection

```bash
factortester-manager server inspect --json
factortester-manager server access --json
factortester-manager jobs list --scope server --limit 20 --json
factortester-manager storage usage --json
```
