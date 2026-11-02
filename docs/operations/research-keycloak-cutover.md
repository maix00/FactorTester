# Research 授权迁移与验收

适用于 ADR-190 的 Research、Report 与 Profile 授权迁移。此文记录准备和验收程序；目前没有完成严格模式切换，也不能仅凭阶段性迁移日志删除旧授权数据。

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
