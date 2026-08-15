# Server-declared access scripts

This directory contains optional, non-secret operator scripts referenced by a
server's `.settings` `management_access[].script.id` value. The Manager API
serves a script only to an authenticated Manager, verifies the declared
SHA-256 before serving it, and never executes it.

Keep every script self-contained, reviewable, and below 4 MiB. The matching
settings entry must provide a safe filename, content type, SHA-256 digest, and
whether downloading it requires the local operator credential. Scripts must
read credentials from the operator's local tool or environment; never commit
keys, passwords, bearer tokens, host private paths, or generated credentials.

The Manager CLI saves a downloaded script with owner-only permissions. An
operator must review it and choose how to run it; downloading it is not an
authorization to mutate a host, container, tunnel, peer, or release.
