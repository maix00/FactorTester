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
3. 每个同步事件由唯一 home Manager 发出，携带稳定实体 ID、来源 Manager、单调来源序号/版本、操作和必要的目标状态摘要。断线期间事件保留；恢复连接后，可同步机构级配置，但用户及其权限只在该用户尝试登录公网时按需同步，不能批量推送所有用户。接收端按事件 ID 幂等应用到自己的 Keycloak，成功验证后推进相应游标；删除与撤权不得因分页、过期或缺字段静默省略。
4. 用户基本资料、组织/层级组、成员关系、组织管理员组和被明确批准可跨 Manager 使用的角色/对象授权可同步。只有 home Manager 明确赋予公网访问资格，且源机构开启同步、目标允许该机构同步的用户，才能触发其本人数据同步。目标 Manager 的设备白名单、公网登录许可和本地 visitor policy 保持本地；源端资格不能自动替代目标端登录授权。每种可同步对象必须声明 owner、映射和授权范围；未知事件版本或未支持授权类型阻止该事件并报告，不能跳过。
5. 同步消息不包含密码、密码 hash、MFA secret、refresh token 或可复用 bearer token。新用户在源 Manager 立即可用；目标 Keycloak 收到用户和权限镜像后仍需完成目标侧凭证初始化，不能伪称凭证已同步。
6. Manager 到 Manager 链路离线时，本地用户继续使用本地 Keycloak 登录；本地权限可继续管理。远端权限变更只在同步成功后对目标 Manager 生效。对端副本的最大陈旧时间与远程访问租约必须配置并可观测；撤权尚未同步时不得把目标端旧权限声称为实时一致。对端身份状态超过租约时，跨 Manager 访问失败关闭，本地 home Manager 的本地用户访问不受影响。

### 跨 Manager 身份上下文

1. 远程调用使用目标 Manager 可验证的服务身份、明确的 audience/scope，以及稳定 `tr_identity_id`、来源 Manager 和本地认证来源摘要；不接受调用者自行声明的用户 ID。
2. 接收 Manager 验证服务调用者后，按本地 Keycloak 已同步的身份镜像和授权规则评估主体与目标对象。来源 Manager 的管理员身份不会自动成为接收端管理员。
3. 不把用户密码、refresh token、完整认证 token 或可复用 bearer token 写入 RabbitMQ 消息、RunSpec、ExecutionPlan 或长期缓存。任务执行只携带完成本次授权所必需的最小冻结主体上下文。
4. 个人显示偏好可以继续经既有 account-domain 同步机制传输，但不得把该机制当作用户/权限权威或新身份同步协议；偏好同步不授予任何权限。

### 可变用户父链与研究可见性（2026-11-02）

组织/层级 Realm Groups 负责委派管理范围；用户之间可由管理员调整的父链使用受保护的
`tr_parent_identity_id`。旧研究 `superiors` 不转换为当前上级的显式用户名单，而使用
Keycloak 原生 UMA `condition` 调用随部署提供的固定 JavaScript policy。策略在 Keycloak
进程内读取当前用户模型，验证同机构、启用状态、唯一稳定身份及无环父链，只授予该资源
明确绑定的只读 scopes。所有者、Profile 归属和单独协作授权不随改挂上级而改变。

这需要可选 scripts preview feature，不需要 Keycloak 源码补丁；不能将实时父链检查
移回 Manager，也不能依赖旧 token 中的父级 claim。查找仅在单个 KeycloakSession 内
有界复用（至多 512 项），请求结束即释放，避免跨请求缓存造成管理员修改后旧权限继续有效。
迁移计划中的父链只是审核和逐 scope 对账基线；审核后层级改变必须重新审核，迁移不得
把管理员修改回滚为审核时的旧关系。部署、真实两端迁移与跨 Manager 撤权验收仍是独立门槛。

## 迁移顺序与清理门槛

1. 在公网和内网各自的 Keycloak realm 创建并核验 Manager 客户端、角色、Realm Groups、层级关系及默认拒绝授权；公网自助注册始终关闭。
2. 从公网控制目录与内网 SQLite 分别导出不含密码材料的快照，逐项比较账号集合、机构、层级、角色、状态和引用完整性。一次性迁移可将已核对的 PBKDF2-SHA256 凭据转换为 Keycloak 原生格式；不导出明文，不覆盖目标已有凭据。这不属于跨 Manager 的日常凭据同步。
3. 为旧主体建立唯一 `tr_identity_id` 映射；将 Job/report、因子/策略/产品组 owner、共享授权、设备、个人设置和 outbox 逐类盘点。跨 Manager owner 映射必须比较精确的对象引用与有效授权集合。
4. 实现并在隔离 Realm 验证可断网恢复的身份变更流：内网创建用户/修改嵌套组权限 → 网络中断期间内网登录和本地授权继续工作 → 恢复后等待具有公网资格的用户尝试登录 → 只同步该用户及其允许同步的权限至公网 Keycloak → 完成目标侧认证 → 重放、乱序、重复、撤权、删除及冲突均有确定结果。
5. 公网与内网 Manager 分别验收浏览器登录、注销、访客低权限身份、公网登录许可、机构与层级管理员、设备管理、对象授权和跨 Manager 任务/数据请求。对端 Keycloak 不可用时本地认证继续；本地 Keycloak 不可用时本 Manager 的受保护操作失败关闭。
6. 只有两端运行版本、同步队列零积压、两侧 Keycloak 受管身份/授权对账一致、历史对象 owner 映射无歧义并完成回退演练后，才能停止旧账号写入并移除旧用户/权限运行实现。迁移脚本只在部署和对账验收后作为迁移代码清理；数据备份按独立保留策略处理。

## 当前实现状态（2026-10-30）

- 两端均运行独立的 Keycloak 26.8.1 realm 和持久化 PostgreSQL。两端原始目录实际均为 6 个用户、1 个机构、1 个层级；早期导出中添加的 default 机构并非真实记录，已从导出器移除。
- 按已授权映射，两端均迁移 3 个保留用户、唯一机构、层级与父用户关系。稳定身份属性、Realm Groups、FGAP、角色、公网登录许可和原密码的原生 PBKDF2 凭据均已写入；旧数据库已备份，未销毁旧行。
- 内网 Manager 已接通本地 realm。真实浏览器通过原用户密码登录、会话检查、管理员目录及注销；隔离验收账号分别验证超级管理员、机构管理员、普通用户的管理员边界与对象 UMA 允许/拒绝。机构外用户直接查询被拒绝。
- 公网 Manager 已实际切换至 Keycloak。两端的超级管理员、机构管理员、普通用户均通过 React 登录入口、会话、管理员目录边界、对象 UMA 允许/拒绝和退出验收。机构管理员查询机构内用户成功、机构外用户返回 403。公网撤去 `public_server:login` 的隔离用户被拒绝且不生成 Manager 会话；访客仅有 access，没有 submit 或 artifact-download。
- 两端已将三个保留用户的 Keycloak 登录名改为经过明确审核的短名。按稳定身份定位后检查整个批次的名称冲突，只更新 username；原 subject、机构、层级、角色、凭据及 `legacy_username` owner 映射保持不变。原超级管理员的短名及既有密码在两端均通过真实浏览器验证。此映射是一次性迁移输入，不是 Manager 登录别名数据库。
- 公网真实登录发现旧的全局设备认证门禁在 Keycloak 成功认证后仍返回 401。交互登录应由 Keycloak 身份及公网登录角色决定；设备白名单只约束自动登录。修正后聚焦 HTTP 测试覆盖有效身份进入与伪造 Cookie 拒绝。
- 旧密码登录页、自建用户目录与主要 ACL 运行路径已移除，但不能宣称所有授权路径均迁移完成：`ResearchCatalog` 仍读取 memberships、authorized_users、superiors，并提供基于 SQLite 的 share-links。这些研究协作授权须逐对象迁入 Keycloak、对账后删除，不能简单删除字段或关闭共享功能。迁移与备份脚本保留到现有对象授权和同步核对完成。
- 联邦身份变更流、按公网许可的登录时懒同步、撤权/离线/重放、已有业务对象授权映射及真实跨 Manager 执行验收尚未全部完成。禁止以两端初始用户集合一致声称联邦同步已完成。
- 隔离的 Keycloak 26.8.1 浏览器试验验证了原生身份代理的一条候选路径：来源角色限定 client scope，机构同步标志映射到 ID token，目标 IdP 检查必需 claim；符合条件的用户在首次代理登录时创建，撤销角色或关闭机构同步后下一次代理登录被拒绝，已有同名不同身份的用户不会自动链接。详细试验可运行 `scripts/test/keycloak_lazy_sync_smoke.py`。这不代表现网同步已经接通；目标端本地密码登录、跨主机 issuer 与 TLS、机构/层级及对象权限映射仍需实现并验收。Keycloak 的[身份代理文档](https://www.keycloak.org/docs/26.8.1/server_admin/)说明，代理首次登录的用户创建与 realm 自助注册开关彼此独立。

## 验收标准

- 同一人的两个 Manager-local Keycloak 用户具有相同且唯一的 `tr_identity_id`；本地 token 仍按各自 issuer 验证，不同步认证凭证。
- 断网期间内网 Manager 可登录、创建本组织用户并管理本地权限；恢复网络后，仅具有公网资格的用户在尝试公网登录时触发本人资料与权限的幂等同步，并对账相关用户/组/角色/对象授权集合。
- 用户在目标 Keycloak 上完成本地凭证初始化后才能登录目标 Manager；跨 Manager 同步不复用密码或 MFA 凭证。
- 未获某 Manager 本地服务角色/组授权时，该 Manager 明确拒绝访问。
- 公网用户无 `public-manager-login` 时不能登录公网；开启公网注册不能绕过管理员创建流程。
- 不同 Manager 的设备白名单、机构角色、对象授权和撤权不会因同一 realm 或联邦连接而自动扩散。
- 旧身份引用映射无歧义，迁移前后有效对象授权集合一致；两端均通过发布验收后才允许移除旧实现。

### 客户端报告与第二个 Manager（2026-11-02）

本机已有报告可在第二个 Manager 已有同一版本时建立本地同步回执：必须重新核验
当前会话、报告所有权、编辑权限、来源包、显示投影及规范化编辑树，并在写回执前
确认本机内容及资源未变；版本不一致仍报告冲突，不能覆盖。此路径只按需核验单报告，不缓存
完整历史。React 客户端也识别该新回执状态。

隔离测试使用真实 Keycloak、CouchDB 和两个不同 Manager 状态的 HTTP 实例；
由于两实例共享进程，测试只替换了进程级部署上下文。同一 realm 的新报告在
Keycloak 资源创建时冻结研究和报告的绑定；第二个 Manager 可在同一所有者、
绑定一致且当前写入及分享授权均有效时复用该资源，不重建任何授权。历史资源
若没有绑定，不能自动认领。单报告迁移入口会核对原 Manager 的登记回执、报告
记录及 Keycloak 资源，核验恢复到独立 CouchDB 的记录；迁移前后比较全部已验证
活跃人类用户的七个资源权限和该资源的 UMA 策略，只写入绑定元数据，不修改授权。
实际执行还要求两类备份校验、Keycloak 恢复演练、授权写入静默和持久日志；
备份来源与恢复演练需要操作员核验，入口不会把校验和当成恢复成功证明。
测试环境共用对象存储，不
代表两台独立服务器或两个 realm 的双向同步已验收。

隔离 Keycloak/CouchDB 测试将旧报告的绑定字段移除，在分享权限已撤销时从
保留原修订的 CouchDB 记录恢复副本执行该入口；测试 realm 的三个人类账号在
迁移前后的七种决策及资源策略一致，撤销的分享权限没有被恢复。测试使用的
Keycloak 备份是校验流程夹具，不是实际 realm 恢复演练；真实服务器尚未运行
此迁移，也未完成历史权限的全量对账。

### 浏览器会话续期

浏览器将 Keycloak refresh token 保存在同源 HttpOnly、SameSite=Lax Cookie；
HTTPS 使用 Secure。Manager 在 access token 到期前 30 秒按需兑换，
刷新后的 access token 仍经过 Keycloak 验证及机构/公网准入判断。
未验证的 JWT 到期字段仅用于调度续期，不能授权。显式 Bearer 请求不使用浏览器续期凭据。

并发兑换按刷新凭据合并，结果最多缓存 10 秒、256 项；缓存只消除
旋转竞态，不替代身份或对象授权。HTTP keep-alive 的每个请求清空临时状态。
认证服务短暂故障返回可重试的 503，不删除 Cookie；无有效登录返回 401，
不误称为设备认证失败。注销清除访问和刷新 Cookie，并使用 Keycloak 注销入口。
