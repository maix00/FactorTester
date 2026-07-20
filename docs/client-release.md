# Client installation and recovery

## Requirements

- macOS 13 or newer for `GTHTClient.app`;
- Python 3.11 or newer to run the bootstrap CLI;
- HTTPS access to the public FactorTester client release;
- a FactorTester server account for remote research.

No server source checkout, database driver, or local backtest engine is needed.

## Release profile

Create a local JSON file. It contains paths and a manifest URL, never a
password or token:

```json
{
  "schema_version": 1,
  "release": {
    "manifest_url": "https://github.com/maix00/FactorTester-Client/releases/download/v0.1.0/release-manifest.json",
    "install_root": "~/Library/Application Support/FactorTester"
  }
}
```

The trusted release public key is fixed inside the client wheel. A profile
cannot replace it.

## Install and update

Always inspect the deterministic plan before mutation:

```bash
factortester client bootstrap --profile client-profile.json --dry-run --json
factortester client bootstrap --profile client-profile.json --json
factortester client status --profile client-profile.json --json
```

Updating uses the same transaction:

```bash
factortester client update --profile client-profile.json --dry-run --json
factortester client update --profile client-profile.json --json
```

Artifacts are downloaded into a staging version, checked against the signed
manifest, materialized without dependency resolution, and health-checked
before `current.json` changes.

## Login and local profiles

The password is read interactively and is not accepted on the command line:

```bash
factortester configure --base-url https://factor.example
factortester login --username <account> --keep-login
factortester logout
```

One interactive login can persist locally for later Agent processes. Logout
removes that local authenticated session. macOS adapter secrets are stored in
Keychain; profile files contain only opaque credential references.

The macOS UI manages the human profile and all Agent profiles. Each Agent has a
stable provider-neutral ID and an explicit research scope. Approvals still
happen in the relevant Agent conversation; the settings UI only displays
completed approval facts.

## Local adapters

Signed adapters are installed under the selected release. Their processes,
health checks, and loopback Web URLs are managed deterministically:

```bash
factortester client adapter list --release-profile client-profile.json
factortester client adapter start vibe-trading \
  --release-profile client-profile.json --profile-id <agent-profile>
factortester client adapter stop vibe-trading \
  --release-profile client-profile.json --profile-id <agent-profile>
```

Vibe-Trading runs on its own loopback service and is embedded into the macOS
application with `WKWebView`. Startup never downloads source or dependencies.
Its executable or runtime location is selected through the local profile.

## Rollback

Rollback selects an already installed and verified version; it neither
downloads assets nor rewrites data:

```bash
factortester client rollback --profile client-profile.json --json
factortester client rollback --profile client-profile.json \
  --to-version 0.1.0 --json
```

If health checks fail, keep the failed receipt and logs for diagnosis, retain
the current healthy pointer, and report the manifest hash and source revision.

## Backup and clean reinstall

Before a destructive acceptance test:

1. record the install receipt, checksums, running jobs, database path and
   database identity;
2. make a database backup and pass SQLite `integrity_check`;
3. stop client-owned adapter processes;
4. remove only version directories named in the client receipt;
5. reinstall from the published GitHub manifest;
6. compare database identity and retained row counts, then test login/logout,
   macOS UI, Vibe UI, and one bounded research job.

Never derive a cleanup root from an empty value, `/`, the home directory,
`Documents`, or the repository parent. Never delete a database, market-data
bundle, factor workspace, Keychain item, or local research memory as part of a
client reinstall.
