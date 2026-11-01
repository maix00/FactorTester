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

## 2026-11-02 设备与身份只读盘点

02:50（Asia/Taipei）检查本机暂存 Manager 与公网 Manager 的运行环境。两侧
Keycloak 中 MaxJJW、testA、testB 均启用，三个账户的稳定身份及旧限定身份
摘要逐一相同。本机暂存 Manager 未配置 PostgreSQL 控制库，且其 JSON 设备
登记文件不存在；这不代表其他内网实例没有旧设备。

公网 `remote-main` 的 PostgreSQL 只读事务中，按上述三个账户的精确旧身份
过滤，设备记录分别为 8、4、2 条，共 14 条；均启用且来源为 `remote-main`。
当前表不存在旧的 `public_access` 和 `quota_exempt` 列。这个汇总不核验设备
公钥与 Keycloak 资源/策略的逐条对应，也不验证当前的有效登录授权；不得把
计数或身份摘要相同当作迁移完成。公网运行版本尚未包含当前设备授权模块，
需要在切换前完成逐对象权限对账及真实撤销/登录验收。盘点未修改两端数据。

随后使用公网当前配置的 Keycloak Protection API 对上述 14 条启用记录逐一查询
按当前合同生成的设备资源名；14 条均未找到对应资源。查询只检查资源存在性，
没有模拟用户令牌作有效决策，也不能推断其他命名空间不存在历史授权。此结论
要求在切换前完成冻结快照、授权创建及允许/拒绝对照，禁止将其视为迁移完成。
复核清单摘要同时绑定设备字段和 Keycloak 稳定身份、主体与启用状态，主体变更
必须重新审核；清单只输出主体证据摘要，不输出主体原文或设备公钥。

已新增受控设备授权 staging 核心：复核摘要绑定 Manager、Keycloak issuer、
旧记录及主体；写前和每条写入前重新比较快照，已有资源不自动重新授权，写入
前先落盘意图日志，异常中断不能自动重试。新资源使用 Keycloak create-only
路径并由策略求值核验，日志不包含用户名、主体或密钥。隔离 Keycloak 实测了
迁入、所有者与其他用户的真实令牌决策、撤销后的拒绝。新增命令入口可按单个
主体从已恢复的独立 PostgreSQL 数据库生成审核清单并执行 staging；执行前要求
设备写入静默、Keycloak 备份校验和和新日志，数据库连接地址只从环境读取。
它尚不支持其他设备存储，也不验证 Keycloak 备份本身能够恢复；两类数据库的
实际备份恢复、全部旧权限逐项对账及跨 Manager 授权验收仍是切换前提。
staging 回执始终不表示切换就绪，尚未在真实服务器执行。

随后在一次性 PostgreSQL 17 和 Keycloak 26.8.1 容器中，用 `pg_dump` 和
`pg_restore` 恢复测试设备记录，通过命令入口审核并 stage，验证所有者令牌
允许、其他用户令牌拒绝、撤销后原令牌拒绝。容器已删除；其中 Keycloak 备份
文件只是校验逻辑的测试夹具，并非 realm 导出或恢复演练，不能视为服务器切换
前的备份验证。
