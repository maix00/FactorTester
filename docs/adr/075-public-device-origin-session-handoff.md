# ADR 075: Canonical public-IP device authentication

## Status

Superseded by ADR 077.

## Decision

Browser device authentication has one origin only: the configured public
Manager HTTPS IP endpoint. The browser private key is enrolled and used there;
ngrok never performs device challenge, device verification, or session handoff.

ngrok is only a convenience visitor ingress. Its navigation redirects once to
the public IP with a short-lived visitor grant. The grant allows the public-IP
compliance page to display the visitor entry; it does not authenticate a user
and it does not carry a private key or Manager session.

If the browser has no public-IP device key, it remains on the compliance page.
Direct public-IP navigation never displays the visitor entry without a valid
ngrok grant and never redirects back to ngrok.
