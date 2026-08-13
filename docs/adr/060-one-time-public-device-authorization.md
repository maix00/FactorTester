# ADR 060: One-time authorization across Manager origins

## Status

Accepted.

## Context

Browser `IndexedDB` is scoped by origin. A key generated at an internal
address such as `http://192.168.1.20:7998` cannot be read by a browser opened
at `https://203.0.113.10:7998`. Storing only the public key in PostgreSQL does
not solve that origin boundary, and storing a browser private key on the
server would defeat the device-key design.

## Decision

The internal, authenticated Settings page creates a short-lived,
single-use authorization grant bound to a target `server_id`, target Manager
endpoint, authorizing account, and a concrete language snapshot. PostgreSQL
stores only a SHA-256 token hash, owner, target, language, expiry, and audit
metadata. A JSON store is retained for single-node development only. If the
user preference is `system`, the issuing Manager resolves the current request
language to `zh-Hans` or `en` before creating the grant; the target page does
not replace that snapshot with its browser's language.

The target public Manager accepts the grant only over HTTPS. Its dedicated
`/device-authorize` page generates a new non-exportable P-256 WebCrypto key in
the target origin, submits the public key with the one-time grant, atomically
consumes the grant, enrolls the device, and issues the normal session cookie.
The raw grant is removed from the address bar immediately and the page has no
third-party resources. The ordinary compliance page has no registration
button; it only attempts already-existing credentials for that same origin.

Each enrolled public-device key is permanently bound to the account that
created its authorization. Redemption and later challenge verification
automatically issue a session for that stored account; a client-supplied
username is never an authentication input. A public device-gated Manager also
rejects password login, so an approved key cannot be reused to select another
account. Changing the binding requires revocation and a new authenticated
authorization.

The protocol is not browser-specific: a native Swift client can use the same
challenge/signature and enrollment payloads while keeping its P-256 private
key in Keychain/Secure Enclave. It must not depend on browser IndexedDB.

Neither client stores a hard-coded public IP. The internal Manager projects
online HTTPS public targets from its federation registry, ordered by observed
latency, load, and stable server identity. Both clients also display the
current Manager, server-reported internal addresses, and current/inferred
public target so that an address change is visible before switching.

For minimum-necessary access auditing, a device record may contain only a
coarse client type/name, enrollment source IP, and most recently observed IP.
Raw User-Agent values, browser fingerprints, MAC addresses, IMEIs, and
location are not persisted. Public pages select Chinese or English from the
same shared string catalog used by the Swift and Web clients.

## Consequences

- No domain or DNS is required; an HTTPS IP address with port 7998 is a valid
  target endpoint.
- A copied or replayed authorization link is limited by target binding,
  expiry, and one-use consumption. It must still be transferred through a
  trusted channel.
- A device registered from the internal origin is not silently treated as a
  device registered from the public origin.
- A changed public address is learned through Manager federation rather than
  requiring a client release or a manually embedded IP.
- Every public Manager still rejects ordinary login/registration for an
  unapproved external device and shows only the compliance page.
- PostgreSQL is authoritative for explicit user language preferences, while
  each Manager keeps a five-minute local projection. Existing local values are
  migrated on first authenticated access; database outages preserve cached
  reads but reject preference changes explicitly.
