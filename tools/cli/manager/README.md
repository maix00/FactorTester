# FactorTester Manager CLI

`factortester-manager` is the CLI-Anything-style application client for an
authenticated FactorTester Manager. It calls the real Manager HTTP API and
7997 capability data plane; it does not reimplement FactorTester behavior or
administer the host.

## Command groups

Use `--help` at each boundary and `--json` for automation:

- `server inspect|access` — read server-owned identity and access metadata;
- `jobs list|ports` — inspect FactorTester Jobs;
- `artifacts list|download` — inspect or transfer Job artifacts;
- `storage usage` — read storage usage;
- `research-graph versions|active|set-default` — manage graph activation;
- `services list|start|stop|restart-api|restart-bundle|force-stop` — control
  Manager-owned FactorTester services;
- `client release` — publish an authorized FactorTester client release.

Host/container/tunnel/repository transport is deliberately outside this CLI.
If a server declares operator access in its settings, `server access --json`
displays that non-secret metadata without executing it.
