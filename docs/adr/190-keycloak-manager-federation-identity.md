# ADR-190：联邦 Manager 的本地 Keycloak 与身份权限同步

- 状态：分阶段迁移
- 日期：2026-10-29
- 决策范围：TradeResearch Manager、Keycloak、Manager 联邦、用户注册与身份引用

## 背景

多个 Manager 需要互相发现计算与数据能力。公网 Manager 可能离线，而内网 Manager 仍须完成本地登录、机构用户管理和授权变更；内网恢复连接后，还要把新增用户与权限变更同步到公网。因此单一在线 Keycloak 不能是唯一可写节点。

Keycloak 26.8 的 multi-cluster v2 是高可用方案，不是分区期间可独立写入的多主方案：其跨集群数据库必须同步复制，官方建议数据库提交延迟低于 5ms、要求低于 10ms；网络断开会导致请求失败或延迟。公网与内网 Manager 不能依赖这类同步链路来实现离线管理。参见 [Keycloak multi-cluster v2](https://www.keycloak.org/high-availability/multi-cluster-v2/introduction)。

当前旧账号表还被登录、对象 owner、个人设置和同步投影使用。删除账号表前，必须确认登录与授权已由各 Manager 的 Keycloak 承担，并为既有对象 owner 建立精确的稳定主体映射。仅证明两边用户名列表相同，不足以证明身份迁移已完成。

## 决策

### Keycloak 部署与本地可用性

1. 每个 Manager 部署自己的 Keycloak realm 和独立数据库；Manager 的 OIDC 登录、用户管理、Realm Groups、角色、FGAP 和对象授权由本地 Keycloak 提供。一个 Manager 或其 Keycloak 离线，不阻止另一 Manager 继续认证和管理其拥有的用户/权限。
2. 每份 Keycloak 数据库只供同一 Manager 的 Keycloak 使用。不得让两个 Manager 直接共用 Keycloak 数据库，也不得复制 PostgreSQL 数据目录或 Keycloak 内部表。
3. 公网 Keycloak 使用稳定且浏览器可信的 HTTPS issuer；内网 Keycloak 使用该内网 Manager 客户端可访问的 issuer。两个 issuer 不同，token 的 `(iss, sub)` 只标识本地 Keycloak 身份，不作为跨 Manager 用户合并键。
4. Keycloak 连接池与进程资源单独限额，不进入回测逐 Bar 热路径。各部署可使用本机 PostgreSQL 专用数据库/角色；不得复用 Manager 控制库的表、角色或凭据。

Keycloak multi-cluster v2 可在满足同步数据库和低延迟条件的高可用环境中用于故障切换，但不用于本系统 Manager 间离线写入。数据库支持矩阵见 [Keycloak 数据库配置](https://www.keycloak.org/server/db) 与 [Keycloak 支持的生产配置](https://www.keycloak.org/server/supported-configurations)。

### 身份权威、稳定键与写入归属

1. 每个用户在其所属组织的 home Manager 创建；创建时由该 Manager 的 Keycloak 写入不可变 UUID `tr_identity_id`。该标识在其他 Manager 的 Keycloak 镜像中保持一致，并作为跨 Manager 的稳定用户键和既有对象 owner 映射目标。
2. 本地 OIDC 的 `(iss, sub)` 仍是验证本地会话的权威键；它不跨 issuer 比较。Manager 将已验证 token 的 `tr_identity_id` 解析为平台主体，同时保留本地 `(iss, sub)` 作为审计来源。缺失或重复的 `tr_identity_id` 必须拒绝跨 Manager 身份解析，不得按用户名、别名或邮箱自动合并。
3. 组织及其层级、组织用户和 scoped admin group 由该组织登记的 home Manager 唯一写入。其他 Manager 的副本只读；网络恢复后的并发/来源冲突进入人工审计，不采用 last-write-wins。
4. 全局管理员角色由指定的身份治理 Manager 写入并通过受限同步分发。公网登录许可、设备信任、Manager 本地服务授权和本地访客策略是目标 Manager 的本地权限，不因用户镜像而自动授予或同步。
5. `username`、别名和邮件仅是 Keycloak 管理的可变资料字段，不用于账号合并、跨 Manager 权限判断或对象 owner 的最终身份键。
6. 不得因用户名相同而合并账号，也不得复制密码、密码 hash、MFA seed、refresh token 或其他认证凭证。同步创建到目标 Keycloak 的新用户默认禁用或标记为待凭证初始化，并要求通过目标 Manager 的 Keycloak 邀请/凭证流程完成本地登录设置。

### 用户/权限同步与离线行为

1. 公网仍关闭自助注册。各 Manager 的用户创建操作必须由本地 Keycloak FGAP 授权的管理员通过 Manager 管理 API 发起；内网离线时，内网本地 Keycloak 仍可创建本组织的新用户并即时赋予本地权限。
2. Keycloak 是本地身份和权限的唯一权威存储。Manager 只保留通过现有 Manager Federation 控制通道传送变更所需的有界 outbox、游标、幂等事件 ID 和冲突状态；这些记录是传输状态，不是第二套用户/ACL 权限数据库。禁止直接复制 Keycloak 数据库。
3. 每个同步事件由唯一 home Manager 发出，携带稳定实体 ID、来源 Manager、单调来源序号/版本、操作和必要的目标状态摘要。发送端持久化后重试；接收端按事件 ID 幂等应用到自己的 Keycloak，成功验证后推进游标。断线期间事件保留，恢复后继续发送；删除与撤权使用 tombstone，不得因分页、过期或缺字段静默省略。
4. 用户基本资料、组织/层级组、成员关系、组织管理员组和被明确批准可跨 Manager 使用的角色/对象授权可同步。目标 Manager 的设备白名单、公网登录许可和本地 visitor policy 保持本地。每种可同步对象必须声明 owner、映射和授权范围；未知事件版本或未支持授权类型阻止该事件并报告，不能跳过。
5. 同步消息不包含密码、密码 hash、MFA secret、refresh token 或可复用 bearer token。新用户在源 Manager 立即可用；目标 Keycloak 收到用户和权限镜像后仍需完成目标侧凭证初始化，不能伪称凭证已同步。
6. Manager 到 Manager 链路离线时，本地用户继续使用本地 Keycloak 登录；本地权限可继续管理。远端权限变更只在同步成功后对目标 Manager 生效。对端副本的最大陈旧时间与远程访问租约必须配置并可观测；撤权尚未同步时不得把目标端旧权限声称为实时一致。对端身份状态超过租约时，跨 Manager 访问失败关闭，本地 home Manager 的本地用户访问不受影响。

### 跨 Manager 身份上下文

1. 远程调用使用目标 Manager 可验证的服务身份、明确的 audience/scope，以及稳定 `tr_identity_id`、来源 Manager 和本地认证来源摘要；不接受调用者自行声明的用户 ID。
2. 接收 Manager 验证服务调用者后，按本地 Keycloak 已同步的身份镜像和授权规则评估主体与目标对象。来源 Manager 的管理员身份不会自动成为接收端管理员。
3. 不把用户密码、refresh token、完整认证 token 或可复用 bearer token 写入 RabbitMQ 消息、RunSpec、ExecutionPlan 或长期缓存。任务执行只携带完成本次授权所必需的最小冻结主体上下文。
4. 个人显示偏好可以继续经既有 account-domain 同步机制传输，但不得把该机制当作用户/权限权威或新身份同步协议；偏好同步不授予任何权限。

## 迁移顺序与清理门槛

1. 在公网和内网各自的 Keycloak realm 创建并核验 Manager 客户端、角色、Realm Groups、层级关系及默认拒绝授权；公网自助注册始终关闭。
2. 从公网控制目录与内网 SQLite 分别导出不含密码材料的快照，逐项比较账号集合、机构、层级、角色、状态和引用完整性。一次性迁移可将已核对的 PBKDF2-SHA256 凭据转换为 Keycloak 原生格式；不导出明文，不覆盖目标已有凭据。这不属于跨 Manager 的日常凭据同步。
3. 为旧主体建立唯一 `tr_identity_id` 映射；将 Job/report、因子/策略/产品组 owner、共享授权、设备、个人设置和 outbox 逐类盘点。跨 Manager owner 映射必须比较精确的对象引用与有效授权集合。
4. 实现并在隔离 Realm 验证可断网恢复的身份变更流：内网创建用户/修改嵌套组权限 → 网络中断期间内网登录和本地授权继续工作 → 恢复后按序同步到公网 Keycloak → 新用户目标侧凭证初始化 → 重放、乱序、重复、撤权、删除及冲突均有确定结果。
5. 公网与内网 Manager 分别验收浏览器登录、注销、访客低权限身份、公网登录许可、机构与层级管理员、设备管理、对象授权和跨 Manager 任务/数据请求。对端 Keycloak 不可用时本地认证继续；本地 Keycloak 不可用时本 Manager 的受保护操作失败关闭。
6. 只有两端运行版本、同步队列零积压、两侧 Keycloak 受管身份/授权对账一致、历史对象 owner 映射无歧义并完成回退演练后，才能停止旧账号写入并移除旧用户/权限运行实现。迁移脚本只在部署和对账验收后作为迁移代码清理；数据备份按独立保留策略处理。

## 当前实现状态（2026-10-30）

- 两端均运行独立的 Keycloak 26.8.1 realm 和持久化 PostgreSQL。两端原始目录实际均为 6 个用户、1 个机构、1 个层级；早期导出中添加的 default 机构并非真实记录，已从导出器移除。
- 按已授权映射，两端均迁移 3 个保留用户、唯一机构、层级与父用户关系。稳定身份属性、Realm Groups、FGAP、角色、公网登录许可和原密码的原生 PBKDF2 凭据均已写入；旧数据库已备份，未销毁旧行。
- 内网 Manager 已接通本地 realm。真实浏览器通过原用户密码登录、会话检查、管理员目录及注销；隔离验收账号分别验证超级管理员、机构管理员、普通用户的管理员边界与对象 UMA 允许/拒绝。机构外用户直接查询被拒绝。
- 公网 Manager 仍运行旧应用版本。公网 realm 已准备，但不能将该准备状态称为公网网页登录或应用切换通过。
- 旧用户/密码/权限运行实现已从任务分支移除；业务 owner 引用仍作为数据保留，不作为授权来源。迁移与备份脚本保留到两端部署、真实登录、现有对象授权和同步核对完成。
- 联邦身份变更流、按公网许可的登录时懒同步、撤权/离线/重放、已有业务对象授权映射及真实跨 Manager 执行验收尚未全部完成。禁止以两端初始用户集合一致声称联邦同步已完成。

## 验收标准

- 同一人的两个 Manager-local Keycloak 用户具有相同且唯一的 `tr_identity_id`；本地 token 仍按各自 issuer 验证，不同步认证凭证。
- 断网期间内网 Manager 可登录、创建本组织用户并管理本地权限；恢复网络后变更完整、幂等地同步到公网 Manager 的 Keycloak，并对账用户/组/角色/对象授权集合。
- 用户在目标 Keycloak 上完成本地凭证初始化后才能登录目标 Manager；跨 Manager 同步不复用密码或 MFA 凭证。
- 未获某 Manager 本地服务角色/组授权时，该 Manager 明确拒绝访问。
- 公网用户无 `public-manager-login` 时不能登录公网；开启公网注册不能绕过管理员创建流程。
- 不同 Manager 的设备白名单、机构角色、对象授权和撤权不会因同一 realm 或联邦连接而自动扩散。
- 旧身份引用映射无歧义，迁移前后有效对象授权集合一致；两端均通过发布验收后才允许移除旧实现。
