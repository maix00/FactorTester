# ADR-123：本地 Profile 保持可移植，服务器由客户端绑定

## 状态

目标决策已接受，但截至本次审计为**部分实施，存在代码偏离**。

当前 Swift 实现仍在 `LocalProfileModel.swift` 读取 `server.base_url`，并由
`ProfileLiveProcessController`、研究目录和部分 Profile 页面使用
`profile.serverURL`。这些是待迁移实现，不应在 ADR 中写成“已经完全移除”。

## 背景

本地 Profile 描述用户身份、工作区、Agent 和本地研究状态，不应成为部署或
网络配置。早期 Profile 保存 `server.base_url`，会使服务器或端口迁移破坏
报告引用、研究图命令和本地研究创建，即使客户端已经切换到另一台服务器。

服务器上的 Profile 则可以拥有服务器侧运行时记录；其稳定身份是服务器
`server_id`，不是服务端口。

## 决策

- 客户端 Profile 的目标 schema 为 10，不包含服务器 endpoint 字段；
- 已安装 FactorTester 客户端通过全局客户端配置、显式命令连接覆盖或 Manager
  发出的服务器 Agent capability 绑定服务器；报告 authority 和研究图命令
  使用这个连接，不读取 Profile endpoint；
- Manager 同步从客户端连接或显式 Manager URL 得到地址，不从 Profile JSON
  推导；
- 旧 Profile 加载时一次性丢弃旧 endpoint 并持久化规范化 Profile，不把它作为
  回退；
- 服务器 Profile 可以保留稳定的运行时服务器身份，但不能要求端口写入身份。

## 当前迁移边界

Python CLI/Manager 路径已经以客户端/Manager 连接为主；Swift 的
`LocalProfileModel.serverURL` 及其调用方仍需一次性迁移为客户端连接注入。
在迁移完成前，不能删除该字段，否则会破坏现有研究目录和运行时控制器。
迁移验收必须覆盖切换客户端服务器后，Profile 工作区、研究报告和研究图
引用不被移动、复制或重写。

## 后果

客户端切换服务器的目标行为是不移动、不复制、不改写 Profile 工作区和报告。
没有显式 endpoint 的网络操作必须在客户端未配置时清楚失败，而不能悄悄连回
过期端口。本文记录的是目标边界，不为当前 Swift 偏离提供永久兼容承诺。

## 客户端 CLI 认证与连接交接（#395）

原生客户端完成身份认证后，通过既有 stdin 会话桥接交付当前 Manager 连接、
设备认证会话及该端点已接受的证书。CLI 在内存中先调用当前身份接口核对 principal，
成功后才保存端点隔离的 0600 会话及全局客户端连接。失败不覆盖原会话。
证书作为额外信任锚使用，保留证书有效期和主机名校验；不使用关闭 TLS 校验。
登出清除该端点会话；服务器切换不把旧端点令牌发送给新端点。

普通 Profile 同步使用客户端会话，不读取管理员操作凭据。连接不再强改为 7998，
configure 不再默认 8114；无参数沿用客户端连接，--server-id 从该服务器目录
选择并核对目标身份。服务器的设备认证门禁保持有效，CLI 标记仅开放无敏感数据
的预登录网络目录，不授予业务权限。已认证客户端的 CLI login 直接检查已有会话。
