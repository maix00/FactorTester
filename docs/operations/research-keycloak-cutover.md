# Research 授权迁移与验收

适用于 ADR-190 的 Research、Report 与 Profile 授权迁移。此文记录准备和验收程序；目前没有完成严格模式切换，也不能仅凭阶段性迁移日志删除旧授权数据。

## 可变上下级的迁移进展（2026-11-02）

别名对账修正：Research/Profile 最终比较与 stage 共用同一 Keycloak 精确身份核验。
当前登录名与受保护的 legacy_username 可以映射到同一稳定用户；不再将重复的映射值
误判为多用户冲突。每个实际用户的 subject/稳定 ID/启用状态/机构成员覆盖仍须唯一且完整，
两位用户抢占同一新旧标签、未审核名字、不同用户误合并、同一 Profile 的含糊关联仍拒绝。
此逻辑只用于管理迁移核对，不参与运行时授权。

本机真实 realm 只读核验：3 用户、6 精确新旧名称、3 独立 subject，写入 0。
真实临时 Keycloak 的同一 6 名称/3 用户计划通过重复 stage 的 63 项对账，最终 Profile
比较另通过 9 项决策；多 Profile 同用户的隔离与越权写入拒绝仍有聚焦回归。
相关四组 60 项聚焦测试通过，未执行全量测试。

桌面认证入口同步清理：移除旧 Swift 登录/注册/密码维护、Keychain 密码保存和重放，
以及 Manager CLI 的原生密码调用。原生研究桥只接受当前 Manager 校验过的 Keycloak 身份；
Manager 切换和失权清空沿用同一代次边界。原生账户旧导航进入 React 账户设置，移动端有
账户→设置→主页面返回路径。保留的旧密码条目清理器只有删除操作，无密码读取或授权作用；
它不删除当前设备证明密钥或 Manager 会话凭据。这些客户端源码改动尚未发布。

`superiors` 改为 Keycloak 原生 UMA 的 deployed-script `condition`，脚本源码在
`deploy/docker/keycloak/policies/research-superiors.js`；不修改 Keycloak 核心，不改变
资源服务器的全局 decisionStrategy。它读取管理员维护的实时稳定身份父链，
不使用旧 token 的 parent claim，不生成当前上级名单的长期授权，不新增 Manager 权限存储。
需要部署可选的 scripts preview feature，入口和回退见
[Keycloak 部署说明](../../deploy/docker/keycloak/README.md#mutable-research-hierarchy)。

迁移输入可提供完整的 `organization_id`、`parent_username` 审核基线；只用于迁移前后
逐对象 allow/deny 比较。运行时仍由 Keycloak 当前属性决定。未提供基线的旧计划继续阻止
superiors；不完整、循环、跨机构基线直接拒绝。stage 在写入前及比较后核对 Keycloak
实时父链，管理员在审核后修改层级将阻止旧计划执行，需要重新审核，不能改回旧关系。
Resource/Profile 归属不会随着更换上级而改变；显式协作授权保持独立。

真实临时 Keycloak 26.8.1 演练通过：旧 token 下更换上级、两级上级、明确协作授予和
撤销、禁止额外 write/manage、停用的中间上级、跨机构、循环及缺失父级。真实迁移入口
对一项研究、一份报告和 owner self Profile 执行 3 用户×3 资源×7 scopes=63 项策略
比较，重复执行一致；审核后修改层级拒绝。演练复用既有研究创建/Profile/链接撤权测试。
14 次本机 HTTP 决策样本最大约 0.260 秒，包含冷脚本编译和网络；不是浏览器 p95 或
大目录容量验证，未据此宣称性能最优。

现网内网只读重算计划：3 位用户，10/25 研究可准备迁移、40 资源、20 项显式/成员授权；
另外 15 研究仍需修复，涉及已删除身份的历史引用以及非活跃对象。计划摘要
`2894e3d83385b77844a5ecbf1bc9058cbbfc752109f4deed33417de3317a6226`。
本次没有写入现网 Keycloak/SQLite、重启或部署，不能据此宣称两端权限已经迁移完成。

## 边界

- Keycloak 是目标授权权威；Research SQLite 保留对象、Profile 关联和迁移期间的旧授权输入。迁移日志只记录操作和校验，不提供权限。
- 旧所有者或成员无法唯一映射到已审核的稳定身份时，所属研究与报告标为 `needs_repair`；保留原始记录，不删除、改绑或默认转给管理员。
- 旧规则中“上级”表示该所有者当前的真实上级链。Keycloak Group policy 的向下扩展不能直接表达这个反向关系；在父链变更、撤权、跨 Manager 传播均已验证之前，这些对象不进入自动导入。
- 活跃分享链接、公开访客授权以及归档对象也须先证明等价语义。分享链接仅保存令牌摘要和领取状态；授权仍由 Keycloak 决定。已撤销或过期的链接不能重新启用。
- 独立 realm 之间以已核验的稳定身份建立唯一映射；不能把源 realm 的 bearer 当作目标 realm token，也不能按同名用户名推断为同一人。用户须具备公网访问权限，且只在其公网登录时懒同步；不能批量同步全部内网用户。
- 跨 Manager 的对象访问需要受信任节点证明、在线授权与目标 Keycloak 的独立决策；来源不可达或映射不唯一时拒绝。当前 7997 与 Job 的完整跨 realm 委托尚未接通。

## 盘点与备份

1. 分别在每个 Manager 取得受保护的旧库快照和已审核的用户名到 `tr_identity_id` 映射。锁定迁移范围和身份，不在计划中输出源码、凭据或链接令牌。
2. 暂停所有能修改 Research 权限、层级和 Keycloak 相应策略的写入。仅迁移工具之间的文件锁不能代替应用维护窗口。
3. 用 SQLite 原生备份获得独立副本，做完整性检查并核对授权行摘要；另外备份目标 Keycloak realm、用户和授权服务配置，在隔离 realm 完成恢复演练。备份与回执应仅由运维账户读取。
4. 使用与目标 realm 一致的 issuer 生成计划；文件为 0600，存在即拒绝覆盖：

```sh
python -m scripts.migrations.keycloak_research_stage plan \
  --database "$RESEARCH_DB" --reviewed-directory "$REVIEWED_DIRECTORY" \
  --issuer "$KEYCLOAK_ISSUER" --output "$PROTECTED_PLAN"
```

计划从同一 SQLite 读事务生成原始授权摘要和对象清单；输出只包含汇总和计划摘要。逐项检查 `needs_repair`、对象数量、所有者、成员、显式授权、报告继承与链接状态。即使数量相同，也必须比对引用集合及每一身份的允许和拒绝结果。

Profile 盘点可显式增加 `--include-postgres --postgres-settings <Manager 的 control-database.json>`；连接地址和密码只在进程内使用，不写入终端输出或回执。工具在独立只读、可重复读事务中按指定 principal 分批读取 `control_profiles` 与 `control_account_domain_entities` 的授权字段，并分别核对后者的 payload 与权限 envelope；不会读取会话正文。SQLite、缓存文件与 PostgreSQL 是不同快照，`postgres_checked=true` 不表示它们同一时点一致，更不是切换许可。客户端数据、稳定身份与动态层级仍需单独核对。

单报告的 Keycloak/CouchDB 发布入口为 `POST /api/research/{research_id}/reports/{report_id}/couchdb-publication`。请求包含 `branch_ref`、所选报告的完整 `projection` 和 `expected_revision`；首次发布为 `null`，更新时必须提供上次返回的 CouchDB revision。对应读取入口在该地址后加 `/{publication_id}`，也可使用 `GET` 并指定 `branch_ref` 找到同一发布；附件读取在 `/{publication_id}` 后再加 `/attachments/{object_kind}/{object_id}`。两者都实时校验目标服务器准入及精确报告的 Keycloak scope，发布需要 `write` 和 `share`，读取需要 `read`。无权限、离线、版本冲突或内容哈希不一致均不能写入或返回内容。

此入口只提交显式选择的单个报告及随投影提供的资源，报告与附件在同一 CouchDB 文档中按版本原子提交；每次请求最多 32 MiB，单个资源最多 8 MiB、资源总量最多 20 MiB。客户端本地报告可通过独立的 Keycloak 注册入口首次发布；同一客户端的已发布报告可分批同步。服务器所有者可在电脑客户端显式导入已发布的主分支可编辑源码；导入前后重新核验授权及版本，并比对源码与公开投影，本地已有修改不会被覆盖。导入后的同 Manager 报告可按已保存的来源双向同步。同一 Manager 的客户端会分页发现本人报告并尝试自动导入有可编辑源码的主分支；缺源码、权限撤销或冲突会保留待处理状态并提示。其他分支导入、跨 Manager 自动发布与 7997 分片上传仍未接通。旧 Research 整图的自动出站已停用，旧待发记录留待核对；这不代表旧入站镜像、整个研究的批量共享或历史授权迁移已经完成。

## 隔离演练与分批准备

在临时 SQLite 副本和隔离 Keycloak realm 先执行，不触碰真实业务对象：

```sh
python -m scripts.migrations.keycloak_research_stage stage \
  --database "$RESEARCH_DB" --backup "$VERIFIED_BACKUP" \
  --reviewed-directory "$REVIEWED_DIRECTORY" --plan "$PROTECTED_PLAN" \
  --journal "$PROTECTED_JOURNAL"
```

工具复算计划和 issuer，检查独立 SQLite 备份，锁定同库的迁移执行，再为 **ready** 的完整研究对象组创建 Keycloak 资源和明确的成员/用户授权。资源创建绑定原始摘要和创建标识；已有不匹配的资源、策略或主体会阻止操作，不会覆盖。日志为 0600，只记录引用摘要；它不能用于跳过实际检查。

对每个对象组，工具使用 Keycloak Policy Evaluation，对 realm 全部活跃用户和全部七个 scope 比较允许与拒绝。写入响应丢失或进程中断后，保留计划、备份和日志，用完全相同的输入重试；重试重新查询策略并重新做对账。源摘要、身份目录、目标 issuer 或计划变化时必须停止并重新盘点。演练应覆盖授权冲突、重复调用、故障中断、并发、身份不匹配、链接撤销和不完整数据。

本机临时 Keycloak 已验证资源与成员授权、远端写成功但响应丢失后的恢复、所有活跃用户逐 scope 对账，以及 7997 同一票据撤权前允许、撤权后拒绝。这不代表真实对象已迁移，也不证明跨服务器行为。

隔离环境的严格模式分享链接已通过真实 Keycloak 的创建、领取、签发人授权撤销和链接撤销测试。新链接保存经过验证的签发人稳定身份和 Keycloak subject；领取时重新评估签发人的 Research 读取、管理与目标分享权限，再为经过验证的领取人建立独立 Keycloak 授权。一次性链接在操作 Keycloak 前先持久化领取人预留；如果远端已写成功但响应丢失，只有同一稳定身份和 subject 可以幂等重试。链接撤销禁止后续领取，既有领取授权按原行为保留。

旧链接若没有经审核的签发人映射，或旧的一次性链接已领取却没有可信领取人映射，必须标为 `needs_repair`，不能按显示名推断身份。新的 SQLite 链接元数据和领取恢复记录不参与用户权限判断；它们不等于旧链接迁移完成。领取和撤销通过 SQLite 写事务串行，事务内包含有超时的 Keycloak 调用；尽管这不是行情热路径，Keycloak 缓慢时其他同库写入仍可能等待，实际切换前需要在目标环境测量并确认预算。

准备阶段现可处理目标和身份均可精确映射的有效链接。对象及全部用户的 Keycloak scope 对账通过后，工具重新检查签发人的分享权限，再在同一 SQLite 事务中登记签发者及已领取的一次性链接的领取者；已有不一致记录会使事务回滚。领取者必须已具备迁移后的读取权限，才能记录既有领取状态。重试不会覆盖既有绑定。该能力尚须在两台真实服务器的备份副本和隔离 Keycloak 上演练，并完成新旧允许集合对账后才能用于切换。

## 实际切换和回退门槛

真实导入前重新生成两端计划并报告受影响对象、明确的 needs_repair 和备份恢复证据。需要先实现并验收动态上级、链接、公开访客、跨 realm 在线委托及所有读取/写入入口；对所有保留身份和对象进行逐项正反对账，并独立验收 Manager、7997 和 Job 请求。当前工具 **不生成切换许可**，`cutover_ready` 固定为 false。

在确保旧写入口停用、源快照未变化、受保护的真实验收回执完整之后，才可一次性切换授权读取并验证两端；在此之前不得删除旧表或旧路径。若准备阶段失败，恢复采用经过验证的 Keycloak/SQLite 备份；或逐个核对计划、创建标识与完整当前策略后，由授权运维人员回退本次新增资源。存在其他写入或策略冲突时停止，不能按名称、缺失数据或失败结果推断可以删除。

## 2026-11-02 运行入口切换

Manager 与 7997 数据面共用 Keycloak Research 授权工厂；发布投影不再从旧 visibility 或 authorized_users 推导访问权。React 与 CLI 创建研究统一使用 keycloak-create；研究及报告 API 拒绝旧 ACL 字段。CLI 的 grant/grants 命令直接读写 Keycloak。旧 publication publish/settings/revoke 返回 410，原服务器发布写入方法已删除。

这次代码切换不代表历史对象已经迁入目标 realm。旧 ACL 列仍是迁移输入；旧独立 publication 客户端和旧页面的残余调用仍须移除。部署前必须完成上述逐对象映射、Keycloak scope 对账及备份。当前 Manager CLI 运行时检查返回 401 device authentication required，尚不能通过该主体执行真实迁移或声称部署验收完成。

旧分享链接的本地 ACL 创建、领取和列表代码已删除；创建、领取、撤销均要求 Keycloak 分享能力。报告 HEAD 提交不再自动上传到 Manager，原 notify 模块已删除；显式 CouchDB 发布及已有同步收据仍由客户端同步路径负责。

2026-11-02 补充验收：旧链接演练直接构造历史 SQL 快照，不再调用已删除的生产旧 API。`python -m scripts.test.keycloak_research_link_migration_smoke` 在临时真实 Keycloak 上通过：2 个链接完成绑定、42 个 scope 决策对账。容器由演练自动清理。此结果只证明隔离迁移路径，不代表内网或公网真实业务数据已切换。直接用户授权与分享链接现分别检测所需能力，缺少链接功能不会阻断 Keycloak 用户授权。

本机签名 macOS 宿主验收：`apple/scripts/test-macos-signed.sh -disableAutomaticPackageResolution -only-testing:FactorTester-ClientTests/ManagerConnectionBridgeWebKitTests -only-testing:FactorTester-ClientTests/LocalResearchBridgeWebKitTests -quiet`，xcresult 证明 7 passed、0 failed、0 skipped。此为宿主 WebKit 桥测试，不是人工视觉验收。

`python -m scripts.test.research_publication_keycloak_couch_smoke` 使用临时真实 Manager HTTP、Keycloak、CouchDB，通过单报告及附件、可编辑源码往返、桌面导入、两客户端同步、自动发现、新设备发现及双向同步、已提交资源修改保护、收敛恢复、同一 token 撤销分享/读取/公网准入、撤权后重试拒绝，以及共享 realm 下两 Manager 客户端中转同步。独立 realm 未覆盖；真实内网/公网部署未覆盖。临时容器自动清理。Browser 调用返回 `Local browser use is disabled in Work settings`，所以本轮没有声称页面视觉验收通过。

目录初始化不再执行旧 publication→superiors 授权字段重写，也不再按 owner_ref 自动重建 self 成员及工作区。创建时的关联仍由创建事务和 Keycloak 资源登记处理；历史缺失关系由显式迁移解决。61 项聚焦回归通过，新增重开/重复读取不改变历史 ACL、撤销成员、归档工作区及迁移日志的逐行对比。

独立 realm 补充验收：`python -m scripts.test.federated_report_keycloak_couch_smoke` 通过两套真实临时 Keycloak realm、签名 peer HTTP 和真实 CouchDB。覆盖不同所有者/共享接收人、2 MiB 附件、编辑权限预检、源及目标撤权、同一源会话撤权后再次请求拒绝。浏览器→来源 Manager 网关在该脚本中仍由聚焦测试覆盖，未做浏览器视觉验收；真实内网/公网部署仍未覆盖。

生产 `ResearchCatalog` 已删除公开标记、本地用户名名单、同名 owner、旧层级和本地成员带来的 Research/Report 读取回退，并移除本地账户层级 provider 接口。缺少 Keycloak 授权器时读取抛出 AuthorizationUnavailable；创建在写库前拒绝。历史策略只存于 `scripts/test/historical_research_catalog.py`，作为迁移历史快照/允许集的冻结测试对照，生产目录没有引用。旧 ACL 数据列仍保留为显式迁移输入，不再是生产权限来源。119 项聚焦回归通过；真实临时 Keycloak 验证研究创建、直接授权、链接领取、同 token 撤权及目录撤权均通过，未写旧 ACL。Agent 运行准入和 Profile 成员提供器在该独立检查中分别为测试替身和只拒绝替身，不能据此声称其真实端到端完成。

真实部署只读盘点（2026-11-02）：内网和公网 Keycloak 均为 3 个用户；两端旧 SQLite 均有 25 个 Research、20 个 Report、34 条成员关联，链接分别为内网 0、公网 1。通过已登记的精确 legacy_username 匹配后，两端仍各有 15 条 Research 所有者、9 条 Report 所有者、15 条成员关联引用未匹配。它们是引用次数，不是用户数量；不能由这些计数推导两端引用集合相同。公网已部署源码还没有 research inventory 模块，本次使用只读聚合脚本读取摘要，不修改数据库或 Keycloak。

审核目录支持每个唯一稳定用户显式填写 aliases；当前名和旧名都须在目标 Keycloak 用户当前名或受管理 legacy_username 属性中验证，禁止模糊匹配。多个 Profile 仍以稳定用户身份＋profile_ref 区分；相同用户不同 Profile 不合并。多个旧名映射同一用户同一 Profile 的重复成员关联进入 needs_repair，防止不同角色被静默覆盖。盘点分别输出 reviewed_users、membership_profiles、unresolved_principals 和引用问题次数。

真实内网只读 staging 计划（2026-11-02）：25 个研究中 7 个可完整准备（29 个资源、14 条授权），18 个 needs_repair；没有全局孤立引用错误。原因按研究分组计数：3 个含未验证的动态上级规则、13 个含非活动对象、15 个含未映射 owner、15 个含未映射活跃成员/Profile 主体，原因可能重叠。计划仅在内存中生成，未写 Keycloak、未切换数据库；不能把 ready 视为已迁移。公网部署缺少 inventory 模块，已通过只读 SQL 聚合确认数量和摘要，未向公网传输未发布实现。

CLI 移除旧 `research reports publication settings/unpublish` 和 PublicResearchClient 对应方法、outbox 新建 revoke 操作；授权使用 `research grant/grants`，撤权使用 `research grant --revoke`。历史 revoke 队列只读保留并转为显式迁移冲突，不再请求旧服务端 API或当作成功完成。内容 publication publish 及其旧分支消费者仍需迁往统一 CouchDB 发布路径，未声称旧发布客户端已完整移除。

React 登录切换：移除密码、密码确认、机构注册字段，以及 POST /auth/login 和 /auth/register 的客户端回退；账户菜单移除自建注册。只允许明确的 keycloak provider 启用 OIDC 登录；旧/未知/缺失 provider 显示不可用并允许重试，保留合规和公网访客入口、注销与原生会话通知。桌面/移动静态包已重建，未重新下载依赖。35 项模型/桥测试、登录组件 DOM 渲染检查及 TypeScript 通过；DOM 检查不是视觉验收，Browser 仍被 Work 设置禁用。真实内网 public entry 返回 keycloak、关闭注册。

旧 Research 整图同步退役：Manager 不再把 ResearchCatalog 绑定到 account-domain 自动同步器；同步服务不再 backfill、materialize 或自动合并研究整图。新建整图写入与旧冲突回写拒绝；旧待发项原样保留并标记 research_sync_needs_review，即使旧 feature flag 为真也不能发送。入站旧整图不覆盖本地目录，使用现有冲突表记录 ref、来源 revision、删除状态及内容 SHA-256；不把未经 Keycloak 验证的原文复制到用户冲突视图。原文留在远端权威库供显式迁移。重复观察幂等，游标正常推进，pull 明确返回 retired 数量并在本次同步报告 incomplete。历史已缓存整图保留在库内，但从普通目录列表排除；未生成 tombstone。

此修改后真实隔离 Manager HTTP＋Keycloak＋CouchDB 的单报告发布、两客户端同步、撤权、冲突保护和共享 realm 跨 Manager 演练通过。旧整图模块的剩余离线实现及历史数据最终清理仍需核对后完成，不代表真实两台服务器已切换。

旧整图代码移除：删除 `account_domain/research_sync.py`、`research_merge.py` 和仅覆盖旧 PostgreSQL 整图机制的 smoke；ResearchCatalog 不再保留 synchronizer/scheduler 入口，account-domain 不再新建旧 merge-base/intent 表或写入 merge-base。已存在的数据表不在启动时删除，仍留给有备份的显式迁移核对。删除已被真实 Keycloak+CouchDB 跨 Manager 演练取代的旧 peer 测试；分支测试改为验证入站旧图及 tombstone 均不能覆盖同一用户两个 Profile 的独立分支；资源补偿测试直接模拟 SQLite 提交前失败与提交后连接清理失败。56 项聚焦测试通过；真实服务器迁移和部署尚未完成。

移除旧整图模块后，独立 realm 的真实临时 Keycloak＋CouchDB＋签名 peer HTTP 演练再次通过（2 MiB 附件、编辑预检、双端及同会话撤权）。演练容器已由脚本清理；此回执不代表现网发布。

旧在线报告导入入口退役：删除 ResearchCatalog 的旧 `migrate_reports`/失败重写实现及旧报告身份合并助手、Manager 自动发现旧报告函数、CLI 的 `migrate-reports`/`migrate-existing-reports` 和客户端方法。旧 HTTP 地址明确返回 410，不再接受旧 ACL 或导入时重建权限。历史快照生成逻辑仅迁入测试专用 oracle，生产模块不可调用；实际权限迁移使用 `scripts/migrations/keycloak_research_stage.py` 的已审核逐对象计划。75 项聚焦回归通过，包括旧入口不发现/不写入、CLI 移除、现行 CouchDB 路由及事务补偿。

2026-11-02 设备迁移补充：设备 inventory/stage 工具可用 `--manager-state-root` 读取所选 Manager 的既有控制库设置，复用环境优先于设置文件的运行规则；不启动 ManagerState 或初始化 schema。19 项聚焦测试通过。使用临时真实 Keycloak＋PostgreSQL 的 `scripts.test.keycloak_device_smoke` 通过备份恢复与 CLI 迁移、所有者允许、其他用户/密钥拒绝、同 token 撤权拒绝，临时容器自动清理。

实际只读设备盘点：两端均 3 个稳定用户、6 个精确新旧用户名；匹配 14 条设备记录，全部属于公网 `remote-main` 且启用，内网盘点正确报告 outside_manager。尚未证明实际 Keycloak use 授权。公网 entrypoint 将控制库 secret 仅导出给其子进程，普通 docker exec 的环境缺少该 URL，不可据此声称 Manager 未配置控制库；采用与 entrypoint 相同的受保护配置来源后，已完成只读聚合并确认上述所有权。公网已部署版本没有新版 keycloak_device 和 keycloak_policy_evaluation 模块，当前未做线上迁移或发布。不得把启用标记或临时演练当作现网切换完成。

2026-11-02 身份标签与真实实例核对：本机 `/app` 使用用户授权的 MaxJJW 账户完成真实 Keycloak 网页登录，`/api/session` 为超级管理员，username 保留受管理的旧主体标签，研究/报告接口分别返回 10/11 条可见记录。登录名、跨 Manager 的 tr_identity_id、realm 内 sub 和历史 tr_username 必须区分；保留历史引用不等于创建新用户，也不能被用作本地权限绕过。随后直接检查目标 Keycloak 命名空间，现有三个稳定用户的 10 个研究和 11 个报告均缺少对应资源，故当前实例尚未满足新授权路径切换验收。认证成功与资源授权迁移完成是不同结论；本次登录可能触发身份懒同步，不能称为纯数据库只读。

研究授权演练增强：`scripts.test.keycloak_research_grant_smoke` 现在使用生产 identity_mappers 和 UserSessionVerifier，从真实 token 验证三个不同登录名对应其历史主体；Research 与 Profile 均使用真实 Keycloak 授权器，新增同用户 self/work、多用户同名 work 的隔离及同 token 撤权验证。撤销一项 Research read 不会错误地撤销独立的 Profile read，所有实际 read 来源撤销后才拒绝；旧 owner/member 元数据不能恢复权限。真实 Manager HTTP＋Keycloak＋CouchDB 的可编辑报告、两客户端/新设备双向同步、冲突恢复及共享 realm 的双 Manager 演练亦再次通过。Agent 运行准入仍是明确测试替身；另两个 smoke 使用的 NoProfileGrants 测试辅助类尚保留，不据此声称其 Profile 路径全部已覆盖。
