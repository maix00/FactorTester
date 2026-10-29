# ADR-190：联邦 Manager 共用 Keycloak 身份权威

- 状态：分阶段迁移
- 日期：2026-10-29
- 决策范围：TradeResearch Manager、Keycloak、Manager 联邦、用户注册与身份引用

## 背景

多个 Manager 需要互相发现计算与数据能力，但它们不应靠复制用户表来建立互信。若每个 Manager 各自创建同名用户，密码、角色、机构关系和撤权时间可能分叉；用户名也不能作为跨 Manager 的稳定身份键。

当前旧账号表还被登录、对象 owner、个人设置和同步投影使用。删除账号表前，必须确认登录与授权已由 Keycloak 承担，并为既有对象 owner 建立精确的主体映射。仅证明两边用户名列表相同，不足以证明身份迁移已完成。

## 决策

### 身份权威与稳定键

1. 一个相互信任的 Manager 联邦域使用一个 canonical Keycloak issuer 与 realm。联邦域内各 Manager 验证同一组签名令牌，并以 `(iss, sub)` 作为主体身份。
2. `username`、别名和邮件仅是 Keycloak 管理的可变资料字段，不用于账号合并、跨 Manager 权限判断或对象 owner 的最终身份键。
3. 需要连接不同 Keycloak realm 时，必须通过显式的 identity brokering/link 建立身份关系；不得因用户名相同而合并账号，也不得复制密码、凭证或整套用户目录。

### 注册与 Manager 可访问性

1. 用户由有权管理员在 canonical Keycloak 中创建；公网和内网 Manager 均不开放自助注册。
2. 新用户只在 Keycloak 创建一次。所有共享该 realm 的 Manager 因而能识别同一 `sub`，但每个 Manager 必须独立检查本地服务的访问角色、机构/层级范围和目标对象授权。
3. 公网登录需要单独的 `public-manager-login` 权限；内网 Manager 的访问按机构与层级授权。公网权限不得从“属于某机构”自动推导，公网设备白名单也不得因内网信任而自动扩散。
4. 用户创建和角色/组变更不通过 RabbitMQ、Manager Federation 或账号 outbox 复制。Manager 联邦传递的是受限的服务请求，不是用户目录同步协议。

### 跨 Manager 身份上下文

1. 远程调用使用目标 Manager 可验证的服务身份、明确的 audience/scope，以及最小化的原始主体标识 `(iss, sub)` 与来源 Manager 标识。
2. 接收 Manager 验证服务调用者后，仍按自己的 Keycloak 授权规则评估该主体和请求对象；来源 Manager 的管理员身份不会自动成为接收端管理员。
3. 不把用户密码、refresh token、完整用户资料或可复用的 bearer token 写入 RabbitMQ 消息、RunSpec、ExecutionPlan 或长期缓存。任务执行只携带完成授权所必需的最小冻结主体上下文。
4. 个人显示偏好可以经既有 account-domain 同步机制传输，但必须按 `(iss, sub)` 归属并使用既有 outbox/cursor/conflict 生命周期；这类资料同步不授予任何权限。设备信任与 Manager 登录许可保持目标 Manager 作用域。

## 迁移顺序与清理门槛

1. 在 canonical realm 创建并核验 Manager 客户端、角色、Realm Groups、层级关系及默认拒绝授权；保持公网自助注册关闭。
2. 从公网控制目录与内网 SQLite 分别导出不含密码材料的快照，逐项比较账号集合、机构、层级、角色、状态和引用完整性。旧密码 hash 不导入；缺少可验证联系方式的用户由管理员在 Keycloak 中安排凭据初始化。
3. 为旧用户名建立到唯一 `(iss, sub)` 的冻结映射；将 Job/report、因子/策略/产品组 owner、共享授权、个人设置和 outbox 逐类盘点迁移，并比较迁移前后的有效授权集合。
4. 公网与内网 Manager 均配置到同一 issuer/realm 后，分别验收浏览器登录、注销、访客低权限身份、公网登录许可、机构与层级管理员、设备管理、对象授权、跨 Manager 任务/数据请求及 Keycloak 不可用时的拒绝行为。
5. 只有两端运行版本、Keycloak 权限结果和历史对象引用都通过核对后，才能停止旧账号写入并移除旧用户/权限入口。旧数据备份按独立保留策略处理；不能将停用、隔离和删除混为一步。

## 当前实现状态（2026-10-29）

- 公网 Manager 通过已校验 TLS 的会话读取到的 `/api/session` 未包含 Keycloak `sub`；当前观察到的会话不能作为 Keycloak 登录验收证据。
- 本机内网 Manager 容器未配置 Keycloak/OIDC 环境，保存的 CLI 凭据访问本机 `/api/session` 返回未登录。可见的本机 Keycloak 容器与 Manager 不在同一网络，不能作为已经接通的 canonical realm。
- 公网与内网旧目录的只读快照目前均为 6 个账号、2 个机构记录、2 个层级记录；账号集合、机构/层级 ID 和导出的非密码字段一致，引用完整性检查为零问题。这只是旧目录对账，不代表 Keycloak 用户或授权已迁移。
- 迁移脚本当前负责只读导出、结构化层级组规划和不暴露身份值的集合/字段对比；尚未创建 canonical realm 用户/组/策略，也未迁移现有 owner 引用。因此目前不得删除旧账号表、认证路径或权限存储。

## 验收标准

- 两端同一个人得到相同 `(iss, sub)`；没有 Manager 间账号或凭证复制。
- Keycloak 中创建用户后，两端都能识别其身份；未获某 Manager 的服务角色/组授权时，该 Manager 明确拒绝访问。
- 公网用户无 `public-manager-login` 时不能登录公网；开启公网注册不能绕过管理员创建流程。
- 不同 Manager 的设备白名单、机构角色、对象授权和撤权不会因同一 realm 或联邦连接而自动扩散。
- 旧身份引用映射无歧义，迁移前后有效对象授权集合一致；两端均通过发布验收后才允许移除旧实现。
