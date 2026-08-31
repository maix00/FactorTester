# ADR 115: Server Profile Agent 使用本地 FactorTester CLI 能力

## 状态

已接受

## 背景

服务器上的研究身份由 Manager 启动 Agent。Agent 的隔离 `HOME` 不应读取
用户浏览器 Cookie 或宿主机的 `~/.factortester`，但每次执行
`factortester product-library`、任务查询或研究命令都不应要求人工再次配置和登录。
同时，服务器内已有 Manager 时，目录查询不应绕到公网端点产生额外流量。

## 决策

1. Profile Agent 启动时由同一 Manager 签发短期、进程绑定的非管理员会话，
   绑定 `principal`、`profile_id` 和当前 `claim_id`。它不是模型供应商的
   `FACTORTESTER_AGENT_TOKEN`，也不复用浏览器 Cookie 或用户密码。
2. Manager 将本地控制端点、令牌和绑定元数据写入 Profile `.codex` 下的
   0600 私有文件，并通过 `FACTORTESTER_CONFIG`、
   `FACTORTESTER_AGENT_CAPABILITY_FILE` 和 `FACTORTESTER_HOME` 交给 CLI。
   CLI 读取能力文件并在 HTTP 请求中附带 Bearer 与 Profile/claim 头。
3. 本地端点优先使用实际 Manager 监听端口的 loopback 地址；容器部署可用
   `FACTORTESTER_MANAGER_LOCAL_ENDPOINT` 指定 Docker 私有服务地址。该地址
   加入 Agent 的 `NO_PROXY`，不得因为 Mihomo 或 HTTPS 公网策略回流公网。
4. Manager 只对来自 loopback/私有网络、且令牌和 Profile/claim 均匹配的请求
   允许本地 Agent 绕过公网 HTTPS 重定向和设备来源门禁；普通请求的安全策略
   不变。Agent 会话不在 Manager 重启后恢复。
5. Agent 停止、替换、启动失败或 Manager 撤销时，删除私有能力文件并撤销
   会话。CLI 无能力文件时仍保持原来的用户配置/登录行为。

## 后果

- 服务器上的研究身份可以直接执行已安装的 FactorTester CLI，无需手工
  `configure` 或登录。
- 7998 的本地目录与控制请求不经过公网；7997 的数据传输仍使用已有数据面
  能力，不因 Agent 自动登录而改变权限。
- 该能力只赋予研究用户权限，不赋予 Manager 管理权限；新增模型供应商只需
 继续使用同一 Profile 能力，不需要把供应商密钥暴露给 CLI。
