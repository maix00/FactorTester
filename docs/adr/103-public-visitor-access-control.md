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
3. After a successful `visitor-password` login, the web client may generate a
   non-exportable P-256 browser key in the existing origin-local IndexedDB.
   It submits only the device id and public JWK to `/api/devices/enroll`; the
   private key never leaves browser storage.
4. The server derives `quota_exempt` from the live session authentication
   method and a fresh allowlist check.  It ignores any client-supplied flag.
   Such automatic browser devices are stored in the shared `control_devices`
   table, do not consume the ordinary three-device quota, and remain visible
   and revocable to super administrators.  Normal password and native-client
   enrollments continue to use the ordinary quota.

## Consequences

- A normal browser can become a persistent approved device after an
  allowlisted visitor login without sharing a private key between IP and
  ingress origins.
- A private window may create a temporary, separately registered browser key;
  the server intentionally does not claim to detect that mode.  Revocation,
  audit metadata, and the explicit `quota_exempt` marker remain the controls.
- `public_device_count` continues to mean ordinary quota-consuming devices;
  `public_device_total_count` includes automatic allowlisted devices for
  truthful UI and compliance counts.
- The existing device registry and IndexedDB store are reused.  No duplicate
  device-authentication protocol or device-cache table is introduced.
