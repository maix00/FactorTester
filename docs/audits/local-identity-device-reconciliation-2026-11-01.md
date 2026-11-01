# 本机身份与旧设备对账（2026-11-01）

范围：本机测试 Manager `local-feat-docker-staging`；这是局部运行时修复和只读盘点，不代表公网迁移完成。

## Keycloak 登录

浏览器使用已有 MaxJJW 身份登录时，OIDC 完成后 Manager 返回 `server_authorization_unavailable`。只读检查发现 GTHT Realm Group 存在，但无内网 Manager 绑定，当前 Manager 的 Realm Group 也不存在。`inspect_internal` 未发现其他机构或 Manager 的绑定冲突。

备份并校验本机测试 Keycloak PostgreSQL 后，使用管理员身份执行现有 `keycloak_server_admission` 迁移工具，创建 Manager 绑定组并双向绑定。保留受保护迁移回执；Manager 原有受限服务账号未扩权。迁移后该服务账号能重新验证绑定，浏览器以 MaxJJW 完成真实登录，并打开 React 研究列表。没有在本次操作中修改公网 Keycloak。

该测试绑定不包含联邦节点公钥指纹；这次登录验证不证明跨 Manager 联邦建立，也不证明用户、对象和设备权限迁移完成。

## 旧设备记录

本机测试 Manager 的有效控制库配置指向 PostgreSQL。单主体、只读盘点显示：

| 主体 | 旧设备记录数 | 说明 |
| --- | ---: | --- |
| `maxjjw`、`testa`、`testb` | 各 0 | 仅按这些新登录名查找，不能据此判定旧用户无设备 |
| `GTHT@MaxJJW@392452984564` | 8 | 全部记录的来源为 `remote-main`，不属于本机测试 Manager |

本机 Keycloak 能唯一解析这条历史用户身份。按本机 Manager 分类时 8 条均为 `outside_manager`，没有授予本机设备权限；盘点未核对公网 Keycloak 中的实际设备授权。下一步应在公网权威身份域核验同一稳定身份、来源、撤销状态和逐设备授权，比较完整引用集合并处理冲突，不能用新登录名下的零条记录代替迁移对账。
