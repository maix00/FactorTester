# Manager-local Keycloak

This stack is a persistent identity authority, separate from node test realms.
Use an owner-only environment file and import directory outside Git. The realm
must disable self registration on the public Manager. The private listener is
reachable on the existing Manager Docker network as `tr-keycloak:8080`; the
browser issuer is the canonical Manager origin followed by `/identity`.

Configure the Manager with `TR_USER_OIDC_ISSUER` ending in
`/identity/realms/<realm>`, `TR_USER_OIDC_BACKCHANNEL_URL=http://tr-keycloak:8080/identity`,
`TR_KEYCLOAK_PROXY_BACKEND_URL=http://tr-keycloak:8080`, and its confidential
client/authorization credentials. Secrets must be in protected host files or
an owner-only environment file, never in the import source tree in Git.

Public deployments should provision a dedicated database and restricted role
in the existing PostgreSQL, connect it to this stack's private database
network, and set `TR_IDENTITY_DB_URL`. On hosts without PostgreSQL, enable
`--profile bundled-db` and use `jdbc:postgresql://identity-db:5432/tr_identity`.
Neither database port nor the Keycloak administrative health port is exposed.

Before cutover, back up both the old user directory and any existing identity
database; review exact account/group/role/object mappings; run hierarchy and
object authorization parity checks. `--import-realm` only bootstraps an absent
realm; it is not an update or migration mechanism. Recreating containers keeps
the database volume. Never use `down --volumes` for deployment or rollback.

Run with `docker compose --env-file <protected-env> -f compose.yaml up -d`.
Use the same arguments plus `ps` and inspect the readiness health check. A
healthy Keycloak is not a successful Manager cutover. Complete browser login
through `scripts/test/keycloak_browser_oidc.py`, not a direct token request.

Set `TR_IDENTITY_MANAGER_IPV4` to a reserved free address in the Manager network,
excluding its gateway and the static addresses of Manager, databases and brokers.
Keycloak must not dynamically acquire a stopped Manager's fixed address during
host restart. Record the reservation in the protected per-host environment file;
recreate only Keycloak after changing it, preserving the identity database volume.
