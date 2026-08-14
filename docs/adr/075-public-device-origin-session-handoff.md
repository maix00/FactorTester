# ADR 075: Cross-origin public device authentication uses a one-time session handoff

## Status

Accepted

## Context

The public Manager is reachable through both the canonical HTTPS IP endpoint
and an explicitly configured browser ingress such as ngrok.  These endpoints
are different browser origins.  IndexedDB, WebCrypto private keys, and
host-only cookies cannot be shared between them, and the private key must not
be copied to the server or placed in a URL.

The previous compliance-page behavior redirected an ingress without a local
device key to the canonical IP immediately.  That made an incognito browser
skip the visitor entry and made a missing credential look like a failed
authentication attempt.

## Decision

1. A compliance page keeps its visitor entry visible when the current origin
   has no local device key.  The page may show a link to the canonical public
   endpoint, but it must not redirect solely because the credential is absent.
   A pre-existing password session does not substitute for the current
   origin's device key when public device authentication is enabled; this
   also covers a private/incognito window carrying an old session cookie.
2. A device verification performed on an explicitly configured ingress may
   return a short-lived, single-use handoff URL to the canonical endpoint.
   The handoff stores only the already authenticated principal, role, target
   origin, and expiry in server-side process state.  It never stores or
   transports the private key or a source-origin session token in the URL.
3. The canonical endpoint validates the target origin, public-server mode,
   secure transport, expiry, and single-use state before issuing a normal
   origin-bound session cookie.  A wrong-target redemption does not consume
   the ticket; a successful redemption consumes it exactly once.
4. Device authentication remains bounded and observable in the browser.  The
   client reports the failing stage (storage, challenge, signing, verify, or
   network), limits automatic retry runs, and includes the safe next path in
   the handoff request.

## Consequences

- An incognito browser can use the configured visitor mode without being
  silently moved to the IP endpoint.
- A registered device can authenticate from the ingress and then continue on
  the canonical IP without weakening browser origin isolation.
- The handoff state is process-local and is invalidated by Manager restart;
  device registration and the public-key record remain unaffected.
- The canonical public IP must be served with a certificate trusted by the
  browser.  A self-signed certificate can prevent the handoff navigation even
  though the application logic is correct.
- A normal account session alone cannot bypass the public device gate, so an
  authenticated user without the current origin's key sees the same
  compliance policy as an anonymous browser.
