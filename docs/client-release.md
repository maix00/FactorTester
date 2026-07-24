# Client installation and recovery

## Requirements

- macOS 13 or newer for `FTClient.app`;
- HTTPS access to the public FactorTester client release;
- a FactorTester server account for remote research.

No server source checkout, database driver, or local backtest engine is needed.

## Install and update

Release operations intentionally have two authorities:

- Publisher: `factortester client release --channel stable|beta ...` performs
  the common clean-checkout, build, runtime embedding, inside-out signing, DMG,
  Sparkle appcast, compatibility manifest, publication, remote read-back, and
  receipt pipeline. Main becomes public only after all GitHub draft assets
  exist. Beta writes immutable assets before switching its appcast and
  compatibility pointers. It never installs an app.
- Client: FTClient's thin SwiftUI update panel delegates discovery, EdDSA
  verification, download, extraction, post-exit replacement, and relaunch to
  Sparkle. It displays one primary action at a time: check, download, or restart.
  It never builds, signs, notarizes, or publishes a release.

There is only one application updater. CLI actions launch or contact FTClient
through its registered URL scheme; FTClient then delegates to Sparkle:

```bash
factortester client app-update check
factortester client app-update download
factortester client app-update restart
```

The CLI never downloads, mounts, verifies, copies, or replaces the application.
`update-app` remains a temporary command-name alias for the Sparkle `download`
action; it is not a second implementation. The read-only legacy
`check-update` JSON command remains available for automation during the
manifest compatibility window.

For the normal macOS installation experience, download
`FactorTester-Client.dmg` from the public GitHub Release, open it, and drag
`FTClient.app` to Applications. On first launch, the signed client safely
retires a matching legacy `/Applications/FactorTester-Client.app`, so Finder
and Launchpad do not retain two visible clients. The GitHub Release exposes only
this DMG. The CLI, research Harness, their Python runtime dependencies, and
approved adapters live inside the signed app Resources and are covered by an
internal hash receipt; users do not download those components separately.

The updater supports Main and Beta channels. Its launch check is throttled to
one request per six hours and runs separately from runtime activation so
research can start immediately. Main reads GitHub's `appcast.xml`; Beta reads
the configured FactorTester server's `/api/client/releases/beta.xml`. A channel
cannot be changed while an update session is active.

Every distributed Main and Beta build currently uses the same persistent
self-signed identity (`FTClient Beta Release`, certificate SHA-1
`E6F25D4B158C8FA4AE585E9C374AE9FAC7AFC81A`), bundle identifier, and Sparkle
public key. The public certificate fingerprint is pinned so a different
self-signed certificate with the same display name is rejected. Renaming or
replacing that certificate would change the designated requirement and can
make macOS request Documents, Keychain, Automation, or other privacy
permissions again. Channel selection changes only the feed and release
eligibility; it never changes the app identity. Sparkle's EdDSA signature is
the archive authenticity boundary. A future Developer ID transition is a
separate, explicit identity migration; it must not happen implicitly during a
Main publication.

Sparkle verifies the appcast's EdDSA enclosure signature before accepting the
archive and uses its updater/helper processes for safe replacement after the
main app exits. The app's own UI never accepts an arbitrary local path.
`SUPublicEDKey` is embedded at build time and private Sparkle signing material
is never stored in the app, profile, log, or release receipt.

During the compatibility window, CLI discovery also supports the compact signed
`stable.json` or `beta.json` manifest. Main and Beta have separate authoritative
sources and legacy trust anchors. Main reads only
`https://github.com/maix00/FactorTester-Client/releases/latest/download/stable.json`.
Beta reads only `beta.json` from the currently configured FactorTester server.
Beta DMGs use their complete SHA-256 as the filename under
`/api/client/releases/assets/beta/`; the server re-hashes the same opened file
descriptor before serving it and retains prior digest-addressed assets so a
client holding the preceding signed manifest can finish downloading. Neither
path queries a database and neither falls back to the other source. Remote URLs
require HTTPS; loopback development servers may use HTTP on `localhost`,
`127.0.0.1`, or `::1` only.

A client profile selects exactly one channel:

```json
{
  "schema_version": 1,
  "release": {
    "channel": "stable",
    "server_manifest_url": "https://factor.example/api/client/releases/beta.json",
    "github_manifest_url": "https://github.com/maix00/FactorTester-Client/releases/latest/download/stable.json"
  }
}
```

The Main URL is fixed by the client; profiles cannot redirect it to another
HTTPS host. The non-selected URL is never requested. GitHub cache ETags are not treated as
content digests; the ECDSA signature is the Main authenticity boundary. The
FactorTester server defines its own ETag as the raw manifest digest in addition
to the Beta signature.
`factortester client check-update --profile client-profile.json --json`
returns the verified version, build, channel, DMG URL/SHA256, minimum client,
mandatory flag, publication time, source, and manifest hash.

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

An Agent can idempotently discover, claim, and register a provider-neutral
profile in one command:

```bash
factortester client profile bootstrap \
  --profile-id maxa \
  --display-name MaxA \
  --server-url http://127.0.0.1:8000 \
  --agent-id research-maxa \
  --source-owner-ref 18717974771
```

The returned `agent_prompt` is the compact hand-off text for any Agent
provider. The source account is recorded only as factor-library provenance
(`factortester://factor-library/18717974771`). It does not become the profile
owner and no source-account password or token is stored. MaxA and MaxB may use
the same authorized initialization source while retaining different profile
IDs, Agent IDs, workspace roots, and research records.

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
