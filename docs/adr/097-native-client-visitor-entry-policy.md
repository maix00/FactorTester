# ADR 097: Native clients use a dedicated visitor-entry policy

## Status

Accepted

## Context

The public Manager has two intentionally different browser entry points:

- the configured ngrok ingress may show the bounded visitor-mode entry;
- the canonical public IP must remain compliance-only for an ordinary browser.

The Swift client and future native clients still need to open the same bounded
visitor experience when they first connect to the public IP.  Treating the
public IP itself as a visitor origin would make the visitor link visible to
ordinary browser traffic and would violate the public-entry policy.

## Decision

Native clients identify the initial Manager navigation with:

```text
X-FactorTester-Client-Access: ftclient
```

The public Manager exchanges that non-privileged marker for an origin-bound,
short-lived client-access cookie.  The cookie only enables the visitor link on
the compliance page and an explicit `/visitor` click can create the existing
bounded visitor session.  It never authenticates a user, registers a device,
or grants API, Manager, or artifact access.

The policy is therefore:

| Entry | Visitor entry |
| --- | --- |
| Direct public IP, ordinary browser | Hidden |
| Configured ngrok ingress | Shown through the existing one-time grant |
| Native client with the client-access marker | Shown through the client-access cookie |

The protocol name is client-neutral so other native clients can implement the
same behavior without adding another Swift-specific exception.  The marker is
not a security boundary; all privileged operations retain their normal session
and device checks.

## Consequences

- The public IP remains compliance-only for normal browser navigation.
- Swift and future native clients can use the public IP without depending on
  ngrok or on a browser-origin IndexedDB store.
- A client marker does not permit login or registration; a registered device
  is still required for public authentication.
- The Web shell owns the visible settings entry.  The native shell no longer
  duplicates it with a top-right settings/update toolbar.
