# ADR-154：研究成员身份与报告分支协作

状态：实施中（Issue #394）。

## 已确认的问题

研究成员与工作区的逻辑唯一键遗漏 principal；两个用户的 `self` 会覆盖。
移除成员只传 Profile 时有歧义，旧服务还禁止移除任何名为 self 的成员。
本机报告正文请求返回 503，入口首页同时显示无在线公网服务器。
报告内容读路径仅查已有路由，没有调用既有的可信发现节点按需激活能力。
这两项是独立问题，不能把测试通过解释为公网链路已经恢复。

## 决策

成员/工作区采用 `(research_id, principal_ref, profile_ref)`。
服务器与运行端不参与用户身份；workspace_id 保留，不能通过迁移重新生成。
移除接口显式接受 principal_ref；旧调用仅在 Profile 唯一时解析，否则拒绝。
拥有者本人的 self 必须保留，其他用户的 self 可独立撤销。
同步仍使用 account-domain research_catalog 信封，完整快照与权限撤销一起传播。

报告正文按需激活已发现且身份验证通过的确切源服务器，复用现有 federation
节点注册；列表不建立连接，不尝试猜测端点，不绕过签名/证书验证。

报告的共享身份为 report_id，分支的逻辑身份应为 `(report_id, branch_id)`；
principal/Profile 是作者身份，服务器只是内容提供者。同一分支只能在版本校验
通过后更新。拥有者选择性整合其他分支，来源分支不被修改。
章节复制应携带源版本与完整子树、资源、绑定，重映射节点和内部引用，并通过
既有报告树事务一次发布。禁止将多个 Profile 的 main 按显示名静默合并。
上述分支登记与复制接口尚待本 Issue 后续实现，不作为本次成员键测试的结论。

## 迁移与回退

旧数据库不得在 Manager 启动时隐式改键。专用脚本
`scripts/research/migrate_research_principal_keys.py` 默认 dry-run，逐对象报告
旧键→新键、状态、workspace_id、计数和完整记录摘要；不读报告正文。
显式 apply 需要新备份路径，写前确认数据没有变化，事务内重建两个约束；
前后完整行摘要必须相同。缺失身份阻止迁移，不生成 tombstone、不重新登记报告。
迁移不能恢复已被历史覆盖的成员，历史恢复须独立审查。
正式环境先停止写者、备份并核查映射，再在授权后迁移。回退须同时恢复旧代码
与备份数据库，不能让旧进程继续写新成员键。

## 验证

合成 SQLite 用例覆盖同名 self、独立工作区、歧义移除拒绝、拥有者保护、
不可借用其他用户成员资格、两副本同步与撤销、显式迁移逐行保留。
正文路由用例覆盖仅激活确切已知来源、不激活未知报告、已有路由不重复激活。
生产连接故障已确认是 LAN 地址短暂不可用时心跳线程退出；提交 dee22bd26
已随 main 0fa6edd5b 发布，本机原报告恢复读取。该结果与按需激活测试分开记录。

2026-09-13 后续实现：CLI `research reports branch-list` 路由补入匹配表，
与页面复用发布目录投影；`branch-read --publication-id ID [--chapter-id ID]`
通过既有跨服务器读通道读取客户端或服务端发布，不将离线降格为不存在。
跨工作包继承在发布 HEAD 前校验并复制本地资源到内容寻址目录；资源缺失、
摘要不符或源 generation 与预期不符均拒绝发布，源 HEAD 不变。
这些是 fork 的基础修复，不等同于跨端 fork CLI、协作分支登记与选择性复制完成。
后者及身份迁移仍未发布，不能把本地聚焦测试视为跨端验收。

## 协作分支登记（未发布）

新增 research_catalog_branches，主键为 `(report_id, branch_id)`，作者使用完整
principal_ref + profile_ref + workspace_id。分支先 reserved，完成内容发布后才
active；发布必须由预留的 Profile 执行，并比较旧 generation/revision。fork
预留记录来源 branch_id/generation/revision，不能将新作者改成报告拥有者。
当前这是服务层能力；HTTP 发布入口还必须核验实际发布对象，不能信任客户端
单方面声明资源已经可用。

元数据纳入原 research_catalog outbox 信封 schema_version=2，继续使用原有
游标与冲突处理。旧 v1 快照只可应用到没有新分支记录的研究；一旦存在协作
分支就拒绝旧快照，不能把旧版本不知道的分支当成删除。旧服务也会拒绝 v2，
因此上线必须协调两端版本，不能将单端聚焦测试视为混合版本兼容承诺。

报告下载授权允许读取已登记编辑者的确切 publication_id，并匹配其 principal
与 report_id；其他同 report_id 的未登记第三方发布不获得报告权限。授权仍在
每次读取时根据当前研究权限检查；撤销编辑者不会删除已贡献的历史分支。

### 可编辑分支快照与对象传输

协作 fork 传递可编辑树，而不是从渲染用 projection 反推源内容。`tree_bundle`
在树锁内冻结可达节点、HEAD、图片与显式本地文件引用；不打包认证信息、运行时
状态、提交 lease 或 SQLite 缓存。导入验证 ZIP 成员、资源哈希、节点哈希、层级、
对象身份与预期源版本，重定位文件引用后才发布目标 HEAD；同 bundle 重试不会覆盖
已经继续编辑的目标。现阶段单 bundle 解包总量上限 64 MiB，超限明确失败，不截断。
Job 附件以及所有引用类型的完整覆盖仍需扩展验收，不能以基础 bundle 测试代替端到端完成。

可编辑 bundle 作为既有 `research_local_resource` 对象经 7997 传输，7998 只保存
索引及哈希。发布键包含 projection revision，已有可编辑发布对象禁止改写；共享分支
目录通过版本比较切换到新 publication_id。服务端发布确认会读回并验证 bundle。
可编辑源码下载独立于普通公开报告浏览权限，仅源作者、报告拥有者或仍有效的
owner/editor 成员可读；7998 与 7997 均应用相同实时授权。上传、断线 outbox 与
对象校验复用现有公共基础设施；尚未上传完的预留分支不视为可用。

### CLI 协作入口

- `research reports branch-upload --profile P --work-package-id W --branch-id B`：
  冻结当前 Profile 已登记的完整树、通过 outbox/7997 上传不可变版本，再比较旧版本
  推进共享分支。断线保留 pending_sync，不能当成已完成共享。
- `research reports branch-fork REPORT --profile P --from-branch SOURCE --branch-id NEW`：
  从目录读取受权源版本，预留目标 Profile 分支，通过下载 ticket 读取 bundle，
  校验后登记本地 Work Package 和报告 artifact，随后执行 branch-upload。
  本地已登记 fork 的重试继续发布原 fork，不重新跟随已变化的源分支。
- 拥有者可将协作者分支 fork 到自己的审阅分支，再使用 `copy-preview` /
  `copy-apply` 选择章节或小节到定稿分支。复制保留来源，且不能绕过目标版本检查。

`test_report_collaboration_workflow` 使用两个独立 Profile store、真实目录、报告树、
发布库和对象存储，验证 fork、独立编辑、版本发布、源前进后的重试和拥有者选择性
复制。网络调用被替代；该测试不替代两端部署、对象通道和浏览器验收。
