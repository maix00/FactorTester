# 联邦计算的 Keycloak 绑定与验收

这份手册描述跨 Manager 的用户委托和计算节点授权；它不包含用户凭据。部署前应由管理员确认双方节点、机构与策略，不能把这里的示例当作已经完成的迁移。

## 信任边界

每次请求使用现有的节点密钥、一次性挑战和已签名的节点地址。节点必须已经登记、租约仍有效，且当前 Keycloak 中的对应 Manager 组必须绑定同一节点 ID 和公钥指纹。用户身份以 Keycloak 的 `tr_identity_id` 为准，不以两端用户名或电子邮件相等为依据。目标 Manager 不把源 realm 的令牌当成本地令牌。

源和目标 Keycloak 均须可访问。源端要在线 introspect 短期 assertion，并实时评估 source UMA `use`；目标端用允许的 IdP 执行 JWT 授权，确认目标用户的相同稳定身份、服务器登录准入及目标 UMA `read` 或 `write`。管理员角色策略要启用 `fetchRoles`，组策略要取当前成员关系；上线前用同一旧令牌撤销授权实际复测。离线、未配置、绑定冲突和身份不一致均拒绝。

节点控制端口使用现有 WireGuard 网络。仅凭私有 IP 不能证明流量已加密：部署前必须确认双方 WireGuard 路由、端口防火墙和密钥；Keycloak HTTPS 自签证书需要配置可信 CA，不能关闭证书验证。

## 两端逐项配置

在每端 Keycloak 原有 Manager 组 `/traderesearch/internal-managers/<manager component>` 中，为**对方** Manager 记录：

| 属性 | 内容 |
| --- | --- |
| `tr_manager_id`（现有内网绑定可用 `tr_internal_manager_id`） | 对方 Manager 稳定 ID |
| `tr_node_key_fingerprint` | 对方已登记的 Ed25519 公钥 SHA-256 |
| `tr_federation_oidc_issuer` | 对方 Keycloak realm 的 canonical issuer |
| `tr_federation_exchange_client_id` | 对方 realm 中签发委托 assertion 的客户端 ID |
| `tr_federation_introspection_client_id` | 本端用于访问对方 realm introspection 的最小权限客户端 ID |
| `tr_federation_authz_client_id` | 对方 realm 中用于实时检查委托许可的资源服务器客户端 ID |
| `tr_federation_authz_resource_id` | 对方 realm 对本端的委托许可资源 ID，其 `use` scope 必须实时核验 |
| `tr_federation_incoming_authz_resource_id` | 本端 realm 对此对方 Manager 的访问资源 ID，其 `read` / `write` scopes 分别控制查询和提交 |
| `tr_federation_exchange_scope` | 可选：本端向此对方目标 issuer 换取 assertion 时需要的可选 client scope |

以上属性必须是单个非空值；不能从未签名公告或浏览器输入自动建立信任。公网 Manager 已有机构与节点指纹绑定，也要保持现有绑定一致；内网端同样需要管理员在本端 realm 确认对公网节点的绑定。按相反方向授权时，两端需分别配置，不得假设一个方向的权限自动适用于另一个方向。

每个 Manager 通过 `TR_FEDERATION_USER_CLIENT_ID` 和 `TR_FEDERATION_USER_CLIENT_SECRET_FILE` 配置本 realm 用于 token exchange / JWT grant 的机密客户端。`TR_FEDERATION_PEER_SECRET_DIR` 指向仅供该 Manager 读取的本机 secret 挂载目录，文件名为对方 Manager ID 的 UTF-8 SHA-256 小写十六进制加 `.secret`；文件内容是本端访问对方 introspection 所需凭据。凭据只放在受保护的本机挂载中，不写入 Keycloak 组属性、浏览器、Job、日志或 Git。认证客户端应仅具有实现交换和 introspection 所需权限。两端 realm 配置须限制可信 IdP、目标 audience、断言有效期与重复使用。

## 每个计算节点的 `use` 权限

目标 Manager 的每个计算节点在 Keycloak Authorization Services 中有独立 `execution_node` 资源。资源引用是紧凑 JSON 数组 `[manager_id,node_id]`，资源名称和 URI 分别由 `keycloak_resource_name("execution_node", ref)` 和 `keycloak_resource_uri("execution_node", ref)` 生成；节点 ID 相同但 Manager 不同是不同资源。管理员应为正确的用户、机构或层级配置 `use` scope 的 Keycloak 策略。不能因为用户可以登录 Manager 或能看到 Bundle 就授予节点使用权。

目录一次批量检查可见节点；自动/手动匹配、预览和提交会重新无缓存检查。尚未注册资源、无 `use` 权限或授权服务不可用的节点不得被选择。资源和策略需要按两端实际节点清单逐一配置与对账；不以重新启动 worker 或修改本地缓存代替授权迁移。

## 部署前后核验

1. 按实际节点签名记录和 Keycloak 组逐项比较 ID、指纹、issuer、客户端、scope 与受限 secret 的安装位置；不输出 secret。核对 `fetchRoles`、IdP 允许列表、单 audience 和短期 assertion。
2. 使用隔离用户验证有权节点可见、无权节点不可见、节点离线时不可选择；选中后撤权，用同一个用户令牌重新预览/提交必须拒绝。
3. 验证异名同稳定 ID 可以映射，同名不同 ID 不可映射；目标节点在线时完成真实 Celery Job，核对 RunSpec、输入、结果和目标 owner；源端离线、目标端离线、源端或目标端撤权时均拒绝，不得读取旧私有 Job 缓存。
4. 测试 7997 字节读取时再次做源用户在线委托和目标对象当前权限检查；不得只依赖先前签发的下载票据。当前这一跨 Manager 路径尚未完整接通，不可把节点/Job 验证等同于字节读取验收。
5. 与旧授权的保护快照逐对象核对。历史身份未映射的记录保持 `needs_repair`，不删除、不更换所有者；未完成逐对象对账时不得启用 Research 严格切换。
