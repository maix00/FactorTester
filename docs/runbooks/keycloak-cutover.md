# Keycloak cutover runbook

## Preflight

```bash
python scripts/migrations/keycloak_accounts.py \
  --db /data/sqlite/unifieddata.sqlite --output /tmp/accounts.json
```

Check:

```text
case_collisions == {}
accounts / organizations / levels counts match the legacy read-only inventory
```

The SQLite source is opened with `mode=ro`; the export preserves organization,
level, parent-level, and legacy account-parent IDs. It never creates a
synthetic organization. If an existing organization has no explicit root
level, the export adds a marked synthetic root *level* so Keycloak group
membership has a well-defined parent. Accounts with a missing or unknown
organization remain unmapped and block apply; they are not assigned to a
`default` organization. Salt/hash/password columns are never exported.

If not empty, resolve manually before import.

## Import

```bash
export TRADERESEARCH_KEYCLOAK_URL=http://keycloak:8080
export TRADERESEARCH_KEYCLOAK_REALM=trade
export TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_ID=tr-admin
export TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET=...

python scripts/migrations/keycloak_roles.py \
  --input /tmp/accounts.json --roles-client-id tr-manager-api
```

The role command is dry-run by default. Review `realm_group_plan`,
`scoped_admin_mappings`, `hierarchy_errors`, and all blockers. Keycloak
Organization Groups cannot be policy subjects in FGAP; the plan uses nested
Realm Groups for organization/level membership and separate administrator
groups as policy subjects. Keycloak FGAP `view-members`, `manage-members`, and
`impersonate-members` cascade through descendants, but a parent `view-members`
grant alone may omit descendant users from search/count results. The plan
therefore includes explicit permission targets for each managed child path;
verify both direct lookup and paged search/count before cutover. The apply path provisions the reviewed Realm Group tree, memberships, and
scoped FGAP policies and verifies their persisted representations. Do not import accounts with
group paths until the Realm Group tree and memberships have been provisioned
and checked in a disposable realm. Unknown roles, invalid flags, malformed
hierarchy, or unmapped memberships block all role assignments. The command
never writes a TradeResearch permission store and never grants scoped
administrators global client roles.

Only after a reviewed plan is complete and the group/FGAP provisioning path is
implemented and verified should operators run the separate user import,
backfill, dual-read, and apply steps. Those live writes require a per-server
backup and explicit migration authorization. Do not remove or clean legacy
records until both Manager deployments have passed the same identity,
organization, hierarchy, and authorization comparison.

Required user-profile configuration is applied by
`server.identity.keycloak_profile.protect_identity_attributes`:

```text
unmanagedAttributePolicy = ADMIN_EDIT
identity attributes: view/edit restricted to admin
```

Identity attributes and OIDC mappers must be explicitly registered. Never use
`ENABLED`: it lets users alter attributes which determine their platform identity.

Keycloak 26.8 Protection API resources remain owned by the resource server.
TradeResearch freezes the user subject in `traderesearch_owner_subject` and
creates an explicit UMA user policy. Registration verifies the subject against
the read-only Keycloak directory; policy responses use canonical usernames.
Existing resources with another/missing subject binding block automatic reuse.

## Legacy object grants

Legacy account roles map as follows:

```text
super_admin -> admin_console:read + admin_console:manage
developer   -> factor:develop
```

`org_admin` and `level_admin` use scoped Realm Group FGAP policies rather
than unscoped client roles. The old local hierarchy API returns 410
in Keycloak mode; its persisted hierarchy fields remain display/migration
input only and cannot grant cross-user access.

Run the old permission inventory against a copy of the existing SQLite file:

```bash
python -m server.permissions.migration_inventory /backup/permissions.db
```

This inventory is read-only and does not disclose subjects or resource refs.
The old `permission_entries` and audit tables are retained on disk for review;
application code no longer reads or writes them. Their object-level grants are
**not** yet automatically imported into Keycloak Authorization Services. Do
not cut over object sharing until each legacy grant has an approved resource,
scope, subject, and policy mapping and the resulting allow/deny sets match.

Before enabling object reads, configure the Keycloak resource server with
resource-specific default-deny policies. Remove or narrow its built-in
wildcard default resource/allow permission; otherwise it can grant access to
unrelated resources. Registering an owner-managed resource does not itself
grant its owner or other users access. Verify owner, group, admin, revoked,
and unknown-user decisions against a disposable test resource before cutover.

## Staged login

```text
TRADERESEARCH_AUTH_MODE=dual
```

`dual` is a migration label only: it accepts verified Keycloak sessions and
never falls back to old local sessions. Password login and public registration
are disabled whenever Keycloak is enabled.

Then:

```text
TRADERESEARCH_AUTH_MODE=keycloak
```

Password login returns `403 keycloak_login_required`.

## Public visitor identity

The visitor entry remains anonymous for the browser. To authorize it, create
a dedicated confidential OIDC client in Keycloak (separate from the Manager
user-login and administrative clients), enable its service account, and
assign only the client roles it needs:

```text
access             required to enter the public visitor mode
submit             optional; permits public test submission
artifact-download  optional; permits artifact downloads
```

Configure the Manager with the issuer, this client ID, its secret file, and
the client ID that owns those roles:

```text
TR_KEYCLOAK_VISITOR_ISSUER=https://keycloak.example/realms/trade
TR_KEYCLOAK_VISITOR_CLIENT_ID=tr-public-visitor
TR_KEYCLOAK_VISITOR_CLIENT_SECRET_FILE=/run/secrets/tr-public-visitor
TR_KEYCLOAK_VISITOR_ROLES_CLIENT_ID=tr-public-visitor
```

The Manager uses the Keycloak client-credentials grant and introspects the
result server-side. It refreshes the policy at most once every 10 seconds;
provider failure denies entry. Assigning/removing roles in Keycloak changes
visitor permissions within that refresh interval. Do not put this secret or
its bearer token in the browser. The browser's HttpOnly visitor cookie only
identifies a pseudonymous per-browser job/quota namespace and is insufficient
to enter visitor mode by itself. The compliance notice remains visible before
the visitor entry, and this does not enable public account registration.

Legacy allowlisted visitor accounts and passwords are not used in Keycloak
mode. Their old records are retained as migration/retention input until a
separate, authorized data cleanup; they do not grant the visitor roles.

## Recovery

There is no local-password authorization rollback mode. An old
`TRADERESEARCH_AUTH_MODE=legacy` value is treated as `keycloak`; unknown values
also fail closed to Keycloak. Recover access through the Keycloak realm's
administrator account and verify Manager OIDC configuration before restoring
service.

## Verification

```bash
python scripts/test/keycloak_oidc_smoke.py ...
python scripts/test/factortester_oidc_e2e.py \
  --base-url http://127.0.0.1:8000 --username alice --password ...
```

For a migrated legacy user, `/whoami` must return the original case-sensitive
username, not the lowercased Keycloak username.

For object authorization, verify the disposable-resource matrix before using
real reports or library objects. The Manager code can register opaque resource
identities and ask Keycloak for decisions, but the real realm policy and
legacy-grant import remain deployment-side acceptance gates.

## Known failure

```text
Keycloak username: gtht@testa@...
whoami username:   gtht@testa@...   (wrong)
```

Cause: callback used the public web client for Admin API. Set:

```text
TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_ID
TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET
```

The admin client must be able to read users.
