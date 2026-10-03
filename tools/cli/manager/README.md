# FactorTester Manager CLI

`factortester-manager` is the CLI-Anything-style application client for an
authenticated FactorTester Manager. It calls the real Manager HTTP API and
7997 capability data plane; it does not reimplement FactorTester behavior or
administer the host.

## Command groups

Use `--help` at each boundary and `--json` for automation:

- `server inspect|access` — read server-owned identity and access metadata;
- `server access check|script download` — check local operator readiness or
  download a server-declared, digest-checked connection script without running
  it;
- `server health|network|federation|database` — inspect FactorTester runtime,
  federation, and redacted control-database status;
- `jobs list|ports|show|cancel|retry|continue|approve` — inspect or explicitly
  act on FactorTester Jobs;
- `artifacts list|download|delete` — inspect, transfer, or explicitly delete
  retained Job artifacts;
- `storage usage` — read storage usage;
- `transfers metrics` — inspect bounded 7997 transfer telemetry;
- `devices list|summary|revoke` — inspect or explicitly revoke public-access
  devices;
- `services list|start|stop|restart-api|restart-bundle|force-stop` — control
  Manager-owned FactorTester services;
- `client release` — build and publish an authorized FactorTester client release.
- `client release-upload` — send an already-built signed Beta package to one
  or more explicit Manager targets through 7998/7997.

Host/container/tunnel/repository transport is deliberately outside this CLI.
If a server declares operator access in its settings, `server access --json`
displays that non-secret metadata without executing it. `server access check`
only checks whether a declared environment variable or macOS Keychain entry
appears to exist; it never prints the value. A downloaded script is written
owner-only, verified against the server-declared SHA-256, and never executed.
`--skip-credential-check` is an explicit operator override for credentials
managed by an external tool. A `wireguard` declaration describes only an
authenticated server-to-server capability; this CLI does not manage peers,
keys, routes, or tunnel lifecycle.

Manager sessions are stored in the platform credential store under a hash of
the complete Manager URL. The same administrator may use this CLI against
multiple servers, but each URL needs its own session; a token from one server
is never sent to another. After an account-name migration, log in to the
affected URL with the current full username; the existing URL entry is
replaced and no username-derived hash is used.
