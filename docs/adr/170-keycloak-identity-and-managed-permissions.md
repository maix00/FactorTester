# ADR-170：Keycloak 身份与可管理权限条目

## 状态

2026-10-29 更新：Keycloak 是所有授权决策的权威；迁移进行中。

原 PermissionEntry/SQLite 方案被以下决策替代。保留后文仅用于识别待迁移的历史规则，不作为新实现规范。

- 平台功能通过 Keycloak client roles 管理。对象权限通过 Keycloak Authorization Services 的 resource/scope/policy 管理。
- 用户、组、管理员、owner 和层级权限均由 Keycloak 策略表达；平台不得以本地角色或 owner 相等绕过决策。
- Manager 验证 Keycloak 会话，API 执行其授权决策；客户端展示不能替代 API 检查。
- 旧规则先只读盘点，逐对象映射、比较允许/拒绝集合与组继承，保留审核与回退材料；替代验收通过后移除旧存储。
- 不允许长期双写或在 Keycloak 不可用时回退到旧存储。缓存须有容量和有效期上限，并披露撤销延迟。
- 当前已接入 Bearer introspection 和助手 client role 检查；网页登录、对象策略、旧授权迁移、桌面助手和完整端到端验收仍未完成。

## 决策

- 身份、组织、下级用户、邀请、realm 角色由 Keycloak 负责。
- 暂不引入 OpenFGA；只有当对象关系继承复杂到 Keycloak 授权策略不可维护时再评估。
- 权限建模为可管理条目，而不是散落在代码中的布尔判断。

## 权限条目

```text
PermissionEntry
  subject        用户/组/组织角色
  resource_type  report | factor_version | strategy_version | job | workspace
  resource_ref   report:<id>:<rev> / factor:v2:... / strategy:v2:... / job id
  action         read | write | publish | approve | delete | share
  scope          self | subtree | organization | explicit
  effect         allow | deny
  audit          创建者、时间、原因、到期
```

规则：

- Keycloak 组织组不能直接用于细粒度授权策略；需要时投影为 realm 组。
- 组织/用户层级不等于对象权限继承；`scope=subtree` 必须显式配置。
- 默认拒绝；owner 只获得声明的 owner 权限。
- 报告/因子/策略的不可变版本只能 publish/read，不能 write 覆盖。
- 权限变更写审计。

## 迁移

- 现有账号/角色导出为 Keycloak 用户/realm 组；
- PostgreSQL 保留 Job/Run 关联和权限投影缓存；
- 双读期比较 Keycloak 决策与旧 ACL；
- 回滚保留旧 ACL 只读；
- 不能同时写两套权限。

## 并行工作流

```text
Workstream 1  Keycloak client + realm/group/org sync
Workstream 2  PermissionEntry model + audit + API
Workstream 3  Report/factor/strategy object permission mapping
Workstream 4  Swift/web login + token/session migration
Workstream 5  Migration/dual-read/rollback + tests
```

文件边界：

- 1 只改 auth adapter/keycloak 配置；
- 2 只改 permission store/API；
- 3 只改对象服务授权检查；
- 4 只改客户端登录；
- 5 只改迁移脚本和测试。

共享接口先冻结，禁止跨工作流直接改文件。
