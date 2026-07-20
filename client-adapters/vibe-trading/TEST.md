# Vibe-Trading Adapter Test Plan

## Scope

The adapter delegates to the official `vibe-trading` executable. It does not
reimplement Vibe-Trading, download dependencies during startup, or persist
credentials.

## Automated tests

- Validate the strict adapter contract and loopback Web UI URL.
- Build a deterministic ZIP with executable launcher files.
- Install the ZIP through the signed client adapter path.
- Start a compatible subprocess through the real adapter manager.
- Verify `/health`, status, embedded URL, idempotent start, and clean stop.
- Reject a missing `vibe-trading` executable with an actionable error.

## Real-backend acceptance

Run the installed official Vibe-Trading CLI with the adapter launcher, verify
that `/health` identifies `Vibe-Trading API`, and fetch the production Web UI
HTML. This acceptance is performed when assembling the signed release, after
the pinned Vibe-Trading runtime has been materialized.

## Current results

- `pytest -q tests/release/test_vibe_adapter.py`: 3 passed.
- Official `vibe-trading 0.1.11` served on `127.0.0.1:7899`.
- `bin/health` accepted the real `/health` service identity.
- `/` returned the production Vibe-Trading HTML application.

The signed-release clean-install test remains the authority for the bundled
runtime rather than this developer-machine smoke test.
