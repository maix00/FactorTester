---
name: cli-anything-traderesearch-manager
description: Use the TradeResearch Manager CLI to inspect authorized Jobs, artifacts, storage, devices, and Manager-owned services.
---

# TradeResearch Manager CLI

Use the installed `traderesearch-manager` command as a Click one-shot CLI. It
calls authenticated TradeResearch Manager APIs and is not a host administration
shell.

## Configure and authenticate

```bash
traderesearch-manager configure --url https://<manager-host>:7998
traderesearch-manager login
traderesearch-manager status --json
```

Check the installed entrypoint and its `--help` before use; older App releases
may still expose `factortester-manager`. Use the App-managed runtime rather than
installing the CLI into Conda, global Python or pipx. Record the installed client
and target Manager versions separately from the source checkout.

Current source supports Keycloak OAuth device authorization when no valid
endpoint-scoped session exists. Start `login` (or `login --no-browser`) and let
the user approve the verification URL and code. Verify the returned Manager
subject before saving credentials; never copy browser cookies, accept a password
grant, or transfer tokens between Manager URLs. An older installed CLI may only
reuse an existing native session. Use the current repository login runbook to
distinguish missing server routes, realm-client scopes, TLS trust and admission
failures; do not bypass validation to make acceptance pass.

## Network topology

Read the target repository's network topology and applicable ADRs. Desktop,
web, mobile and CLI are user clients of authorized Managers. A personal desktop
runtime serves only its current user: it does not register as a Manager-managed
execution node, participate in automatic node selection or accept dispatched
Jobs. A Docker Manager on the same computer is a separate deployment; confirm
its actual institutional role rather than inferring it from localhost.

Client, personal runtime, Manager, managed execution node and Data I/O have
separate lifecycles. Check protocol and capability compatibility across releases;
a stale skill or installed command must not change these roles, silently switch
endpoints or expand access to compensate for a mismatch. Follow current
AGENTS.md, CONTEXT.md and ADRs when a skill copy disagrees with them.

## Command map

- `jobs list|ports|show|cancel|retry|continue|approve`: inspect or explicitly
  change Jobs;
- `artifacts list|download|delete`: inspect or explicitly transfer/delete
  retained artifacts;
- `storage usage` and `transfers metrics`: inspect bounded storage and transfer
  telemetry;
- `devices list|summary|revoke`: inspect or explicitly revoke access devices;
- `services list|start|stop|restart-api|restart-bundle|force-stop`: manage
  Manager-owned service instances;
- `server inspect|access|health|network|federation|database`: inspect safe,
  redacted Manager state;
- `client release`: build and publish an authorized client release.

Use `--help` at each command boundary and `--json` for automation. Never pass
passwords, tokens, private keys, or executable commands through server access
metadata. The CLI does not expose SSH, host restart, container lifecycle,
tunnel changes, repository transfer, or local identity/permission management.

Research Graph and the former server_maintenance resume role are retired. Do not
restore their governance or recovery flows. Research/Report/ReportBranch/Run/Job
use the current repository contracts. Host operations, migrations, publication
and cleanup follow explicit user authorization and repository release rules;
this skill does not grant those permissions.
