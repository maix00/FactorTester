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
| MaxJJW 的 Keycloak 旧身份 | 8 | 全部来源为 `remote-main` |
| testA 的 Keycloak 旧身份 | 4 | 全部来源为 `remote-main` |
| testB 的 Keycloak 旧身份 | 2 | 全部来源为 `remote-main` |

本机 Keycloak 能唯一解析三条历史用户身份。按本机 Manager 分类时 14 条均为 `outside_manager`，没有授予本机设备权限；盘点未核对公网 Keycloak 中的实际设备授权。下一步应在公网权威身份域核验同一稳定身份、来源、撤销状态和逐设备授权，比较完整引用集合并处理冲突，不能用新登录名下的零条记录代替迁移对账。

## 跨 Manager 设备边界

共享控制库曾允许本机 Manager 按设备 ID 直接撤销其他来源 Manager 的记录。现在撤销和认证绑定仅接受当前 Manager 来源，数据库撤销同时核对来源、用户及公钥，避免作用于已变化的绑定。相关聚焦测试覆盖 JSON 镜像和 PostgreSQL 更新条件；尚未在公网部署或验收。

当前 `control_devices` 仍以设备 ID 为单独主键，而桌面端设备密钥和 ID 在多个 Manager 间复用。因此，在共用控制库的部署中，同一设备分别登记到两个 Manager 仍可能发生主键冲突；上述修复不解决多 Manager 独立登记。需要以 `(manager_id, device_id)` 作为绑定身份，连同挑战、查询、撤销、索引和数据迁移对账整体完成，不能通过覆盖来源或复制权限绕过。

2026-11-02：迁移盘点的分页改为 `(device_id, source_server_id)`，重复检查也按来源区分。在一次性、内存文件系统的隔离 PostgreSQL 17 容器中建立复合主键测试表，写入 502 条合成记录，其中同一设备在两台 Manager 的记录跨越 501 条分页边界。实际 SQL 读取完整保留两条；对其中一台执行现有撤销更新后，另一台仍启用。容器在实验结束后删除。这只验证盘点和已实现的撤销 SQL，**不证明生产 schema、登记或完整迁移已完成**。
