# ADR 076: Public device sessions are bound to the canonical IP origin

## Status

Superseded by ADR 077.

## Decision

Sessions created by browser device verification store the authentication method
`device` and the exact canonical public-IP HTTPS origin. A public Manager
accepts that session only on the same origin.

Visitor-password sessions created after the explicit public allowlist visitor
login are also bound to the canonical public-IP origin. Password sessions and
legacy sessions without origin metadata never bypass the public device gate.

There is no cross-origin `device-handoff` endpoint or authentication path.
