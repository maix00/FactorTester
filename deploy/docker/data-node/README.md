# Data-only host service

This Compose runs only the bounded `data-io` cache producer. It has no Manager,
Celery worker, Nautilus runtime, Job database, or task queue. Mount the same
host-owned Bundle directory, cache directory, and Unix socket into explicitly
trusted same-host consumers. The cache is derived, bounded, disposable Arrow
IPC data; original Bundle files remain read-only.

This deployment currently supports **same-host Unix consumers only**. It does
not expose a network file API and cannot serve another machine yet. Cross-host
Arrow Flight, TLS, Keycloak service authorization, and end-to-end throughput
acceptance are still required before advertising this host as a remote data
source. Nautilus workers on the data host are optional and are deployed
separately; this Compose never registers an execution node.

Use one stable `TR_DATA_NODE_ID` for every same-host consumer that must share
this cache namespace. Keep `TR_DATA_IO_SOCKET_ROOT` on the same kernel, grant
the socket only to trusted Manager/worker containers, and set an aggregate
host memory budget before increasing cache or query limits. Do not mount
Manager credentials or writable Bundle directories into this service.
