# ADR 043: Split FTClient app and Python runtime release artifacts

## Status

Accepted. The Sparkle delta step is implemented; app-only payloads and
independent runtime releases remain staged follow-ups.

## Context

The Sparkle payload currently contains `FTClient.app` and a frozen Python
runtime. A small Swift change therefore produces a full DMG of roughly
125 MB. The runtime also contained two copies of the same PyInstaller binary:
one named `factortester` and one named
`cli-anything-factortester-research`.

## Decision

1. The runtime has one frozen executable. The research command is an executable
   shell entrypoint that selects the Python module through
   `FACTORTESTER_ENTRYPOINT`; its receipt is still hashed and verified.
2. Fresh installs keep a complete installer asset. Sparkle updates will move to
   an app-only payload once the installed-runtime fallback is shipped.
3. Runtime artifacts are versioned independently from Swift app builds. A
   runtime manifest will be signed with the existing client release key and
   published beside the channel manifest; the app may activate a newer runtime
   without replacing the app bundle.
4. Release builds expose an architecture dimension (`arm64` and `x86_64`). An
   architecture-specific runtime and app payload is selected by Sparkle; a
   universal installer remains available only as a compatibility fallback.
5. Appcast generation keeps the previous app archive and asks Sparkle to create
   delta payloads. Normal releases retain full DMGs for rollback and first
   install; delta assets are content-addressed and served by the same immutable
   asset route. A local Beta `--delta-only` release publishes only the delta,
   keeps the previous full archive as its base, verifies the delta over HTTP,
   and removes the newly generated full DMG after the successful readback.
   The Beta publisher discovers the previous channel archive automatically.

## Consequences

The first implementation step halves the duplicated frozen-runtime portion of
the package without changing the user-facing CLI. The app-only and independent
runtime steps require a compatibility window: existing clients must be able to
start from their activated runtime when the Sparkle replacement no longer
contains `Contents/Resources/FactorTester`.
