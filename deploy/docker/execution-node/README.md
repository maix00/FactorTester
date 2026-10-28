# Execution-only node

This Compose starts one Celery worker and one bounded market API, **no Manager,
SQLite replica, CouchDB credentials or second broker**. Use a tested versioned
execution image; configure the owner-only node descriptor and scoped Keycloak
clients before `docker compose --env-file <node.env> config` / `up -d`.
The worker's database is private metadata, not an alternate Job authority.

Manager owns its Job repository, dispatcher and RabbitMQ. The node connects to
that broker with ACLs restricted to its target queue. Distinct Managers use
independent registrations/worker instances; connect independent brokers through
RabbitMQ Federation/Shovel only where routing requires it. HTTP discovery and
market reads do not go through RabbitMQ. No custom message forwarder is added.

Set `TR_MANAGER_ID`, stable `TR_EXECUTION_NODE_ID`, deployment descriptor,
Keycloak issuer/client/secret and explicit audience. Manager needs execution
introspection credentials plus scoped federation and market clients. Tokens
carry `tr_node_id` or `tr_manager_id`; delegated Manager clients must have an
explicit `tr_principals` array and separate `tr:federation:submit` permission.
Never grant node tokens federation submission permissions. TLS/private CA is
required outside loopback; mount the CA with a site-specific override when used.
Do not place credentials in the descriptor, source tree or browser payloads.

Same-kernel containers can mount the same source files/cache directory and use
the same `TR_SHARED_STORAGE_ID`. Their installation/source identities remain
different. Separate machines and Docker Desktop/native macOS cannot share
physical pages. Memory limits (2 GiB worker + 512 MiB market by default) do not
replace aggregate host capacity admission; budget Manager, broker, identity,
databases and OS headroom separately before enabling more nodes.

Only a desktop user with explicit install permission may request local node
installation. This operator Compose does not auto-download or enable a local
node for web/mobile users. Distribution uses the existing signed adapter path;
this file is not evidence that a downloadable node package has been published.
