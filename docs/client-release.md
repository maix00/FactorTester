# Client installation and recovery

## Requirements

- macOS 13 or newer for `FactorTester-Client.app`;
- HTTPS access to the public FactorTester client release;
- a FactorTester server account for remote research.

No server source checkout, database driver, or local backtest engine is needed.

## Install and update

For the normal macOS installation experience, download
`FactorTester-Client.dmg` from the public GitHub Release, open it, and drag
`FactorTester-Client.app` to Applications. The GitHub Release exposes only
this DMG. The CLI, research Harness, their Python runtime dependencies, and
approved adapters live inside the signed app Resources and are covered by an
internal hash receipt; users do not download those components separately.

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

Profile configuration and migration receipts live under
`~/Library/Application Support/FactorTester/profiles`. User-visible workspaces
default to `~/Documents/FactorTester/profiles/<profile-id>/workspaces`.
Each workspace retains its own `owner_ref` and access mode; an authorized
workspace is never relabeled as the profile owner. Large local data is
referenced from `local-data` rather than copied into the profile.

Workspace migration starts with an inventory-only plan:

```bash
factortester client profile workspace plan maxa \
  --workspace maxa-factor-library /path/to/maxa owner 'default$MaxA@1' \
  --workspace shared-187-factor-library /path/to/shared granted '' \
  --output workspace-plan.json
factortester client profile workspace apply workspace-plan.json
factortester client profile workspace verify maxa
```

The plan checks ownership, Git/VS Code/Pyright state, conflicts, and capacity.
Apply copies into staging, atomically switches the profile root, and writes a
rollback receipt. Rollback restores the old profile pointer while preserving
the migrated files for inspection.

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
