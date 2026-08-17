# ADR 103: Central public visitor allowlist and automatic browser enrollment

## Status

Accepted

## Context

Public visitor login was previously controlled by a deployment environment
variable.  That made the policy difficult to audit and meant that two Managers
could not manage the same public-access policy from a single authority.  A
small group of explicitly allowlisted ordinary users also needs a convenient
browser path into the public Manager.

Browser APIs do not provide a reliable, security-grade way to distinguish a
private/incognito window from an ordinary window.  The distinction must
therefore not be used as an authentication condition or as a way to bypass
device policy.

## Decision

1. Store public visitor policy in the shared PostgreSQL control database as
   `control_public_visitor_allowlist(server_id, username, enabled, ...)`.
   The `server_id` scope is explicit, so every Manager sharing PostgreSQL
   reads the same policy for that server.  Environment configuration remains
   only as a compatibility fallback when the central policy API is absent or
   the established local-login outage path is active.
2. Expose allowlist and `control_devices` administration only through the
   super-admin “用户与机构” settings page.  Management reads and writes fail
   with an unavailable response when the central database is not usable; no
   stale local management copy is presented.
3. Device enrollment is available only as part of a successful
   `visitor-password` login for an allowlisted account.  The web client may
   generate a non-exportable P-256 browser key in the existing origin-local
   IndexedDB.  It submits only the device id and public JWK to
   `/api/devices/enroll`; the private key never leaves browser storage.  The
   old internal Manager target-discovery, one-time authorization page, and
   authorization-link redemption flow are removed rather than hidden behind a
   UI-only restriction.
4. The server derives enrollment permission from the live session
   authentication method and a fresh allowlist check. It ignores any
   client-supplied device-policy flag. Every surviving `control_devices` row is
   a public allowlist device; existing rows are migrated to that policy and
   remain visible and revocable to users and super administrators. There is
   no ordinary-device quota or internal/native enrollment path.

## Consequences

- A normal browser can become a persistent approved device after an
  allowlisted visitor login without sharing a private key between IP and
  ingress origins.
- There is no internal-network registration step.  A user must first be
  present in the public-server allowlist; the compliance page explains this
  path and never links to an internal Manager enrollment page.
- A private window may create a temporary, separately registered browser key;
  the server intentionally does not claim to detect that mode. Revocation and
  audit metadata remain the controls.
- `public_device_count` and `public_device_total_count` both report enabled
  allowlist devices for compatibility with existing clients; no quota is
  enforced.
- The existing device registry and IndexedDB store are reused.  No duplicate
  device-authentication protocol or device-cache table is introduced.
