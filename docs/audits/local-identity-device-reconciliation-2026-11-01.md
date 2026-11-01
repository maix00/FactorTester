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

当时的 `control_devices` 以设备 ID 为单独主键，而桌面端设备密钥和 ID 在多个 Manager 间复用。因此，在共用控制库的部署中，同一设备分别登记到两个 Manager 会发生主键冲突；上述修复未解决多 Manager 独立登记。

2026-11-02：迁移盘点的分页改为 `(device_id, source_server_id)`，重复检查也按来源区分。在一次性、内存文件系统的隔离 PostgreSQL 17 容器中建立复合主键测试表，写入 502 条合成记录，其中同一设备在两台 Manager 的记录跨越 501 条分页边界。实际 SQL 读取完整保留两条；对其中一台执行现有撤销更新后，另一台仍启用。容器在实验结束后删除。这只验证盘点和已实现的撤销 SQL，**不证明生产 schema、登记或完整迁移已完成**。

## 2026-11-02：设备登记按 Manager 隔离

同一设备密钥可分别向多个 Manager 登记；其数据库主键应为
`(source_server_id, device_id)`。Keycloak 授权引用仍包含 Manager、用户稳定身份、
设备 ID 和完整公钥摘要；修改元数据主键不创建或转移授权。个人授权核查和管理员
登记列表只检查当前 Manager 的记录；撤销仍需匹配用户及公钥。

新增的 `scripts/migrations/device_manager_key.py` 先逐条输出匿名绑定映射和完整记录散列，并报告
无效身份、重复绑定和外键依赖。执行时锁表重新核对审核摘要，事务内修改主键，
比较迁移前后记录数量与散列；发生差异回滚。该脚本不负责创建或验证数据库备份，
上线前仍须制作并验证完整备份及恢复演练。两台使用同一控制库的 Manager 必须
协调停写并升级：旧版本的 `ON CONFLICT(device_id)` 不兼容新主键。若新主键下
已出现跨 Manager 同 ID 记录，不能直接回退旧主键或丢弃记录，必须先单独审核
映射或回退完整数据库与应用。隔离 PostgreSQL 验证不等同真实服务迁移验收。

## 桌面设备认证的接口缺口

当前 Manager 的 `/api/device/verify` 在验签成功后返回 `requires_keycloak` 和
`login_url`，浏览器还须完成 Keycloak 登录、回调与设备授权检查，才会建立
Manager 会话。此前桌面 `ManagerDeviceAuthenticationService` 仍按旧合同解码
`username` 和 `token`；现已改为校验当前 Manager 的一次性登录入口并交给 WebView，
验签本身不建立或保存会话。设备设置新增显式的原生登记动作；已有有效登记重试
时不会因为 Keycloak 暂时不可用而撤销元数据。macOS/iOS 编译、独立交接地址检查、
服务端聚焦测试和模拟网页交互已通过；Xcode 原生测试执行器在启动时卡住，未能
获得 XCTest 结果。真实 Keychain、Keycloak 回调和 Manager 的端到端登记、登录、
拒绝及跨服务器切换仍需在内网与公网分别实测，不能凭模拟测试声称全部完成。

## 移动端真实登录与设置检查

2026-11-02，iPhone 17 Pro、iOS 26.5 模拟器连接本机 `local-feat-docker-staging`：
以已授权的 MaxJJW 账户通过 Keycloak 页面登录后进入 React 研究台；移动端顶部
通知中心、智能体助手入口以及设置中的 Manager 地址表单可见。登录后重启客户端
仍能进入研究台。这验证了本机的普通网页登录及会话恢复，不代表已验证设备密钥
登记、设备自动登录、拒绝后的退出或跨 Manager 身份绑定。

在同一台模拟器上发现当前地址被重复提交时会停留在交接提示；修复后当前地址
不可重复切换，输入其他地址时按钮可用。移动端表单控件调整至 16px，实际聚焦时
页面不再被 iOS 自动放大和裁切。测试没有提交其他 Manager 地址。

桌面 Debug 包启动时未含内嵌 CLI，出现运行时缺失提示；另发现发布构建实际产出
`traderesearch`，而启动代码只查找旧可执行文件。现已共用路径解析器优先查找
TradeResearch 名称和目录，并保留旧包升级读取；macOS build-for-testing 和独立
路径选择检查通过。尚未生成并启动包含完整运行时的桌面发布包，不能把编译成功
视为桌面研究桥的真实验收。

## 研究报告同步的剩余边界

首次从 Manager 导入的报告，以及已存在本机发布回执的报告，已有按权限检查的
拉取和推送路径。此次为首次导入与后续拉取统一增加了报告包与展示内容的一致性
验证；图片和本地附件在目标设备的安全重命名不会被误判为冲突。

本机创建、只选择单篇报告共享时，Manager 保存的是报告及登记回执，当前
`owned-sync` 只发现 Manager 目录中的研究；另一台全新客户端因此还不能自动
发现这类单篇共享。另一方面，本机身份目录仍按 Keycloak issuer 和稳定身份分开，
研究来源表每个研究只记录一台 Manager。即使两个独立 Manager 已联邦，也不能
据此假定身份或同名对象相同；跨 Manager 同步仍需要验证联邦身份绑定、对象版本、
授权和冲突，不能仅比较用户名或未经验证的稳定 ID。这两条链路完成并经过真实
多客户端验收前，不能宣称研究和报告双向同步已经完成。

本轮另在隔离 CouchDB 3 容器中，使用真实 HTTP 客户端和真实 CouchDB 文档与附件，
验证两个本地客户端对同一 Manager 目录报告的导入、发布、拉取、拒绝授权及冲突
流程；测试通过。Keycloak 授权使用测试替身，研究目录也由测试提供，因此这并非
真实 Keycloak 或跨 Manager 的验收。容器数据位于临时内存文件系统，测试后容器已删除。
