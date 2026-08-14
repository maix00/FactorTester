# ADR 076: Public device sessions are bound to their issuing origin

## Status

Accepted

## Context

The public Manager requires a device proof before serving its UI.  A
successful `/api/device/verify` response creates an HttpOnly Manager session
cookie, but the browser then makes a second request for the requested page.
The request must be accepted as the same device-authenticated origin; treating
every public session as unauthenticated sends a successful device login back to
the compliance page and creates an apparent authentication/network failure.

Password sessions and sessions created by older releases must not become a
bypass for the public device gate.  Browser private keys also remain isolated
by origin, so a session issued for one origin must not authorize a different
origin.

## Decision

1. Sessions created by `login_device` store an authentication method of
   `device` and the normalized request origin.
2. Sessions created by a cross-origin device handoff store
   `device-handoff` and the canonical target origin.
3. On a public device-gated Manager, a session is accepted only when its
   authentication method is one of those two device methods and its stored
   origin exactly matches the current HTTPS request origin.
4. Password sessions and legacy session records without origin metadata fail
   closed and remain on the compliance page.  Existing device keys are not
   migrated or copied between browser origins.

## Consequences

- A device verified directly at the public IP can load the requested page
  immediately after the `verify 200` response.
- The existing ngrok-to-IP one-time handoff remains origin-safe.
- A stolen or stale password session cannot replace the current-origin device
  proof under the public gate.
- Sessions created before this metadata existed require one fresh device
  verification after deployment; no private key or database record is changed.
