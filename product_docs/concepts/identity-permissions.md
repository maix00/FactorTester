## 用户与权限 {#identity-and-permissions}

Keycloak 是 TradeResearch 的身份与权限权威。Manager 验证 Keycloak 会话，并以短时缓存的会话投影服务请求；会话投影不构成第二份可编辑用户或权限目录。

Keycloak 用户、客户端角色、Realm Groups 与 Fine-Grained Admin Permissions（FGAP）分别承载用户身份、平台能力和组织层级授权。机构管理员只能在 Keycloak 配置的组范围内管理本机构及下级；超级管理员拥有跨机构管理能力。原有账号数据迁移必须逐用户核对组织归属、层级和角色，不能把旧数据库镜像继续作为写入权威。

设备自动登录也是用户权限边界：设备凭证与客户端类型应绑定到用户，并由 Keycloak 登录资格和相应的设备政策共同决定。公网登录资格、自动登录设备、客户端下载权限是不同能力，不能由“已登录”推导出来。

机构 Manager 的身份同步采用按用户、按需的方向性同步：只有该用户具备公网登录权限且来源机构允许同步时，公网 Manager 才能在该用户首次登录时核验并同步其身份。离线时，机构 Manager 按本地 Keycloak 规则独立认证；同步恢复后处理有版本和冲突检查的变更。不得将整个机构目录无条件复制到公网。

桌面本机计算包的下载由 Keycloak 客户端角色 `desktop_local_node:download` 单独授权；未配置该角色或未分配给用户时，Manager 拒绝下载。该权限只允许读取经过签名校验的本机安装包，不会注册本机节点、不开放任务派发，也不授予远端 Manager 调用本机进程的能力。

## 管理界面 {#administration}

管理员操作入口位于 React `/app` 的“管理员功能”中；用户、机构、角色和 FGAP 规则由 Keycloak Admin Console 管理。TradeResearch 页面只呈现服务状态、互联状态和受限的管理操作，不保存并行权限表。
