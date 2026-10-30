# ADR-170: Keycloak identity and authorization authority

## Status

Accepted; migration is in progress and production cutover is **not complete**.

## Decision

- Keycloak is the authority for web identity, users, organizations, groups,
  administrative roles, and object-level authorization.
- Manager verifies Keycloak access tokens. A local account role, hierarchy,
  visibility label, stale Manager session, or UI state must never grant
  cross-principal access when Keycloak mode is enabled. The current factor
  source/catalog code still has personal-namespace owner checks; those are a
  residual application-side policy and must be moved to Keycloak before the
  authorization migration is complete.
- Platform-wide capabilities use Keycloak client roles. Object access uses
  Keycloak Authorization Services resources, scopes, and policies.
- The public visitor remains anonymous to the browser, but the Manager treats
  it as an automatically established, low-privilege Keycloak service-account
  identity. A dedicated Keycloak client holds only the `access`, `submit`, and
  optional `artifact-download` visitor roles. The Manager obtains and checks
  that identity server-side; client credentials never reach the browser.
  Visitor cookies and ingress grants only establish an origin-bound,
  pseudonymous job/quota namespace and never authorize a request by
  themselves. The public compliance page remains in front of the visitor
  entry, and public self-registration remains disabled.
- TradeResearch does not maintain a parallel `PermissionStore`, permission
  subject resolver, ACL editor, or permission audit database. Historical
  permission tables may remain on existing disks as read-only migration input;
  deleting those files is a separate data-cleanup operation.
- The Manager's own Keycloak realm is required for local authentication and
  authorization; if that local realm is unavailable, protected operations fail
  closed. A peer Manager or its Keycloak being offline does not block local
  authentication or administration. Federated identity and permission changes
  are eventually synchronized between Manager-local realms; remote access must
  fail closed when the peer mirror exceeds its configured freshness lease.
  Authorization decisions may use only bounded process-local caching; local
  revocation delay must be documented and kept short.
- The local-auth `legacy` mode is retired. Old `legacy` or unknown values fail
  closed to Keycloak; `dual` is only a migration label and also accepts
  Keycloak sessions only. No configuration switch re-enables local identity
  or authorization.

## Role mapping

The migration tool maps known local account roles to existing Keycloak client
roles without inventing users or roles:

| Legacy role | Keycloak client roles |
|---|---|
| `super_admin` / `is_admin` | `admin_console:read`, `admin_console:manage` |
| `developer` | `factor:develop` |

Legacy `org_admin` and `level_admin` are scoped by the old local organization
and level-parent records. The exporter preserves those IDs and the read-only
role planner maps them to nested Realm Groups, with a distinct administrator
group as each FGAP policy subject. Organization Groups are not accepted as
group-policy subjects; only Realm Groups are. A level administrator's group
scope covers that level and descendants, and may assign only administrator
groups within that same subtree. Organization administrators cover that
organization's level roots and level-administrator groups. The group and user
scopes are explicit in the generated plan so delegated user creation and group
membership changes can be audited. Neither scoped role receives
`admin_console` or another realm-wide role. Keycloak cascades `view-members`,
`manage-members`, and `impersonate-members` through descendant groups unless a
more specific permission overrides them. However, a parent `view-members`
grant alone may not include descendant members in search or count results, so
the plan includes explicit permissions for every managed child path and the
cutover must verify descendant queries.

This is a plan, not an applied migration: the current CLI does not provision
Realm Groups or FGAP policies. `--apply` refuses any scoped role until group
membership and exact policies have been provisioned and verified in a
disposable realm. Unknown role names and malformed hierarchy/flags also block
the entire apply; they are not silently promoted or skipped. Global roles are
assigned only to exact existing Keycloak users.

## Object authorization

Job report and versioned-object documents store an opaque Keycloak resource
ID. Resource names do not reveal object references. Their protected API reads
are evaluated with the caller's verified token, resource ID, and requested
scope. Missing IDs or unavailable Keycloak decisions deny access. This path
does not yet cover the SQLite-backed factor-source catalog, its manifests,
or every custom-factor route; those still have owner-based application checks.

Before enabling object reads, the Keycloak resource server must have
resource-specific policies and default-deny behavior. Its built-in wildcard
default resource/allow permission must be removed or narrowed. Registering a
resource with `ownerManagedAccess=true` only allows its owner to manage sharing;
it does not itself create an owner access grant. Policies for owner, group,
admin, and explicit shares must be configured and verified in the target
realm. See [Keycloak Authorization Services](https://www.keycloak.org/docs/latest/authorization_services/).

## Migration and data retention

1. Export accounts without password material and reconcile exact usernames,
   case collisions, organization IDs, level IDs, parent links, and legacy roles.
2. Review the nested Realm Group and scoped-admin FGAP plan. Provisioning and
   disposable-realm verification are required before assigning scoped grants.
   Assign known global client roles only after the whole plan has no blockers.
3. Inventory historical object grants read-only. Compare exact subjects,
   resources, scopes, allow/deny precedence, group inheritance, and conflicts.
4. Translate each supported grant to a Keycloak resource/policy mapping and
   compare effective allow/deny sets against the legacy inventory. Unmapped or
   conflicting rules remain an explicit cutover blocker.
5. Verify login, session expiry/revocation, admin roles, object sharing,
   assistant permission, and Keycloak-outage denial against a disposable realm.
6. Only after those checks may operators select Keycloak mode. Historical local
   tables remain untouched until a separately authorized retention cleanup.

The read-only `server.permissions.migration_inventory` utility reports counts
and conflicts without revealing subjects or refs. Runtime code must not import
or write the retired local permission schema.

## Current implementation boundary

Manager OIDC login, token introspection, Keycloak admin links, assistant client
role gating, CouchDB object resource registration/decision calls, exact-role
migration planning, and read-only legacy inventory are implemented in code.
A Keycloak visitor-policy adapter now reads a dedicated service account's
client roles with a bounded refresh interval. The public visitor route and UI
session projection are gated by those roles; the pseudonymous cookie remains
only a namespace. A real Keycloak realm has not been exercised here. The target realm's policies,
legacy object-grant translation, and migration of factor-source/catalog
authorization are still required before Keycloak can be called the sole
authorization authority end to end. The historical identity database is also
still used for non-authoritative profile/display metadata; it is not the
permission authority in Keycloak mode.
