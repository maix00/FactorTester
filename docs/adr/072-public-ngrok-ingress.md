# ADR 072: Public ngrok ingress and explicit proxy trust

## Status

Accepted.

## Context

The stable `eloquence-drizzly-fencing.ngrok-free.dev` browser origin originally
terminated at a development Mac and forwarded to that machine's Manager 7998.
The public FactorTester Manager now owns the long-lived service and must remain
reachable when the Mac is offline.  The public host still may not open inbound
TCP 80 or 443, and ADR 069 still limits it to two business containers.

An ngrok Agent on the public host can establish an outbound TLS connection to
ngrok and forward the stable HTTPS origin to the already-published Manager
7998.  However, forwarding to a Docker-published host port changes the direct
peer observed inside the application container.  The Manager sees the fixed
transport-network gateway `172.30.186.1`, not host loopback.  If it ignores the
canonical forwarded client address, it treats that gateway as a private-LAN
client, exposes LAN-only network information, and stores the gateway as device
audit metadata.  If it trusts forwarding headers from every private peer, a
direct caller or another container could instead spoof an internal or approved
address.

## Decision

1. The ngrok Agent is a host-level ingress daemon, not a third FactorTester
   business container.  It runs as the unprivileged `ngrok` system user under
   systemd, starts on boot, and forwards
   `https://eloquence-drizzly-fencing.ngrok-free.dev` to
   `https://localhost:7998`.
2. The browser-to-ngrok leg uses ngrok's publicly trusted certificate.  The
   agent-to-Manager leg remains HTTPS and verifies the persisted Manager
   certificate through an explicit CA file.  Upstream verification must not be
   disabled.  The ngrok authtoken remains in an owner/group-restricted host
   configuration and is never stored in Git or a container image.
3. The ngrok Traffic Policy removes caller-provided `X-Forwarded-For` and
   `X-Forwarded-Proto`, then writes exactly one canonical client address from
   `conn.client_ip` and the literal secure scheme.  A multi-value forwarding
   chain is not part of this deployment contract.
4. Manager trusts forwarding headers only when the direct peer is loopback or
   belongs to `FACTORTESTER_TRUSTED_PROXY_CIDRS`.  The public Compose project
   configures exactly `172.30.186.1/32`, the fixed gateway of its `/29`
   transport network.  The setting is parsed once at startup; empty entries,
   malformed networks, and host-bit-bearing CIDRs stop startup instead of
   falling back to broad private-network trust.
5. Even for a trusted peer, Manager accepts only one syntactically valid IP
   and one protocol value.  Missing, malformed, duplicate, or comma-separated
   values fall back to the direct peer and cannot create a secure-proxy or
   public-client identity.
6. Device identity remains the registered public key bound to one account.
   Enrollment and last-seen IPs are audit metadata only; they are neither an
   authentication factor nor required to equal one another.
7. Direct public access to `https://<public-ip>:7998` remains available.  The
   ngrok origin is an additional browser origin and therefore has its own
   origin-local WebCrypto storage.  A user on the public allowlist signs in
   through visitor mode at either origin; that origin then enrolls its current
   browser automatically.  No internal Manager handoff or one-time grant is
   used, and a key stored under one origin is never copied to the other.

## Operations and failure behavior

- No new inbound security-group rule is required.  The Agent uses outbound
  TLS to ngrok; clients reach ngrok's edge on 443, while the public host keeps
  ports 80 and 443 closed.
- A Manager/container restart may briefly return an upstream error through the
  domain; the Agent remains running and reconnects automatically when 7998 is
  healthy.  A host restart restores the endpoint through systemd.
- If ngrok is unavailable, direct IP access on 7998 and server-to-server
  WireGuard communication remain independent and usable.
- A Manager certificate rotation requires the Agent's trusted CA copy to be
  refreshed and the service restarted.  Ordinary image releases retain the
  existing certificate and need no ngrok rebuild.
- The local Mac no longer runs the Agent for this domain.  Restarting a second
  non-pooled Agent with the same URL is a deliberate rollback operation, not a
  normal active/active topology.

## Consequences

- The stable domain is served by the public Manager rather than depending on
  the development Mac.
- Public device auditing records the original IPv4 or IPv6 client address,
  while anonymous LAN-only APIs remain protected.
- Proxy trust is an explicit deployment capability, not an inference from all
  RFC 1918 addresses or Docker membership.
- The public host still has exactly the two business containers required by
  ADR 066 and ADR 069; ngrok lifecycle is independent of FactorTester image
  construction and PostgreSQL recovery.
