# Execution-only node

This Linux Compose starts one Celery worker, one bounded market API, and one
host-local data-I/O/cache service, **no Manager, SQLite replica, CouchDB
credentials or second broker**. Use a tested versioned
execution image; configure the owner-only node descriptor and scoped Keycloak
clients before `docker compose --env-file <node.env> config` / `up -d`.
The worker's database is private metadata, not an alternate Job authority.

Manager owns its Job repository, dispatcher and RabbitMQ. The node connects to
that broker with ACLs restricted to its target queue. Distinct Managers use
independent registrations/worker instances; connect independent brokers through
RabbitMQ Federation/Shovel only where routing requires it. HTTP discovery and
market reads do not go through RabbitMQ. No custom message forwarder is added.

`data-io` is the only cache producer for the Nautilus replay path in this
execution-node Compose. It reads source/catalog files in bounded Arrow batches and publishes immutable
IPC files under the existing shared-cache budget. Workers receive file
descriptors over the private Unix socket and memory-map the same host files;
Arrow bytes do not travel through HTTP or Python. This fast path requires Unix
file-descriptor passing. Nautilus itself supports Windows Server 2022 x86_64,
but this Compose and its FactorTester worker/data-I/O transport are Linux-only;
a Windows node must not advertise execution capability until its worker package,
authentication, source adapters, and data transport are implemented and tested.
The planned Windows/cross-host transport is bounded Arrow Flight; it is not
implemented yet. The chart API still has its chart-specific cache reader. Keep
`TR_DATA_IO_SOCKET_ROOT` on the same host and grant access only to the Manager
and workers allowed to read these installed sources. The bounded chart API
still uses its existing chart-specific adapter and is not yet routed through
this replay data-I/O path.

Set `TR_MANAGER_ID` to the owning Manager's stable identity, and set a distinct
`TR_EXECUTION_NODE_ID` for each installed node. The Compose project maps
`TR_MANAGER_ID` to the legacy cache-scope variable `FACTORTESTER_SERVER_ID` so
the Manager and colocated worker use the same shared-cache authority; it must
never be inferred from the worker container hostname. Point `TR_SHARED_CACHE_ROOT`
at the same host directory the Manager mounts as `FACTORTESTER_STATE_ROOT/shared-columnar`.
Also configure the deployment descriptor,
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

The desktop user's local runtime is a different, private execution option. It
is started by the signed-in desktop user on that user's computer; it does not
register through this Compose, appear in Manager node discovery, or accept jobs
from this or another Manager. The Manager may authorize and serve its signed
download package, but it does not invoke the user's local runtime. This
operator Compose is only for Manager-managed execution nodes and does not
auto-download or enable the desktop runtime. No local-runtime package is
published until a signed catalog entry and matching artifact are installed.
