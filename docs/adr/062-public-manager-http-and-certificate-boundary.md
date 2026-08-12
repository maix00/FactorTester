# ADR 062: Public Manager HTTP and certificate boundary

## Status

Accepted.

## Context

The public Manager is reached directly by IP address on port 7998. There is
no domain or DNS entry, and deployment policy prohibits opening ports 80 and
443. The existing listener used a self-signed IP certificate and wrapped the
entire listening socket in TLS. Consequently, an ordinary
`http://<ip>:7998` request received an empty response instead of being guided
to HTTPS. TLS handshakes were also performed before the threaded request
handler, so an idle handshake could temporarily block later accepts.

A self-signed certificate is cryptographically signed and encrypts traffic,
but its issuer is not in browser or operating-system public trust stores. A
publicly trusted Let's Encrypt IP certificate is not available under the
current port policy: IP validation supports HTTP-01 on port 80 or
TLS-ALPN-01 on port 443, not a challenge on port 7998. IP certificates are
also short-lived and require reliable automated renewal.

## Decision

1. A TLS-configured Manager accepts both protocol prefaces on port 7998.
   Protocol detection and TLS negotiation occur inside each request worker,
   not in the shared accept loop.
2. Plain HTTP never reaches login, device enrollment, federation, or another
   application route. Every HTTP method receives a `308 Permanent Redirect`
   to the same path and query on `https://<public-endpoint>:7998`.
3. HTTPS remains the only secure transport for credentials, sessions, device
   signatures, federation tokens, and application APIs.
4. Ports 80 and 443 remain closed. Deployment must not install or invoke an
   ACME client while that policy is active.
5. Until a managed private CA and client trust-distribution flow are
   introduced, the persisted self-signed certificate is retained. Approved
   clients must explicitly trust or pin it; native clients must not silently
   disable certificate validation.
6. Manager-to-Manager HTTPS may load an explicitly provisioned CA bundle from
   `FACTORTESTER_FEDERATION_CA_FILE`. It augments the operating-system roots;
   hostname verification and certificate-chain validation remain enabled.

## Consequences

- Typing `http://<ip>:7998` leads to the encrypted endpoint without exposing
  a usable plaintext login or API.
- The first plaintext navigation cannot itself authenticate the server and
  remains redirectable by an on-path attacker. Approved users and clients
  should retain an HTTPS bookmark and must never submit credentials directly
  to an HTTP URL.
- HTTP access does not make port 7998 eligible for public-CA HTTP-01
  validation, because that validation is fixed to port 80.
- Browsers continue to warn until the certificate or a future private CA is
  installed in the device trust store.
- A future public-CA migration requires an explicit policy change opening
  port 80 or 443; a future private-CA migration requires a secure root
  distribution and revocation design.
