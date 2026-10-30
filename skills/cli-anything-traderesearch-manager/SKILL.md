---
name: cli-anything-traderesearch-manager
description: Use the TradeResearch Manager CLI to inspect authorized Jobs, artifacts, storage, research workspaces, devices, and Manager-owned services.
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

Complete sign-in through the TradeResearch web or desktop client using
Keycloak. The CLI reuses only an existing session for the configured Manager
URL. It does not accept local passwords or manage users, organizations, groups,
or permissions. Tokens are endpoint-scoped and are never sent to another
Manager.

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
