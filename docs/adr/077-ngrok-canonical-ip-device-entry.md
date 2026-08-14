# ADR 077: ngrok redirects to the canonical IP device gate

## Status

Accepted

## Context

The public browser device credential is intentionally enrolled once on the
canonical public IP origin. The configured ngrok address is a separate browser
origin, so its IndexedDB and WebCrypto private-key storage cannot be shared
with the IP origin. Creating a second public device credential for ngrok would
make one browser appear to be two devices and would complicate the quota and
revocation model.

## Decision

1. A navigation from an explicitly configured visitor ingress receives a
   short-lived, single-use, target-bound grant and is redirected to the
   canonical public Manager IP compliance page.
2. The grant authorizes that target compliance page to display the existing
   visitor-mode entry. It does not create a visitor session or authenticate a
   user. The visitor session is still created only when the user explicitly
   selects the visitor entry.
3. The canonical IP compliance page runs the normal device-key bootstrap. A
   browser with the IP-origin key automatically verifies and enters the
   application; a browser without it remains on the Chinese compliance page
   and can choose the bounded visitor mode.
4. Direct IP navigation without a valid ingress grant never displays the
   visitor entry. Invalid, expired, reused, or wrong-target grants fail closed.
5. The private key and normal Manager session are never put in the redirect
   URL. The redirect contains only the opaque, expiring grant and a safe local
   next path.

## Consequences

- The browser has one logical public device credential and one public-device
  quota entry.
- ngrok remains a convenience ingress rather than an authenticated origin.
- The public IP endpoint must have a browser-trusted HTTPS certificate for
  automatic device authentication to complete.
- Visitor grants are process-local and are invalidated by a Manager restart;
  device registration, accounts, and task records are unaffected.
