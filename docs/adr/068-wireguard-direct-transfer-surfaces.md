# ADR 068：WireGuard 直连传输边界

## 状态

已接受并于 2026-08-13 实施。本决策取代 ADR-067、ADR-065，替代 ADR-057 中的跨节点部分，并更新 ADR-059 描述的 7997 进程边界。ADR-070 进一步说明引导发现，以及应用层直连 overlay 与物理 WG 对等节点的区别。

## 背景

ADR-067 假设部分 FactorTester 节点长期位于 NAT 后，因而引入传输专用 SSE 命令、源推送、目标拉取、连接所有者、relay rendezvous 和 SSH 反向隧道兼容路径。当前部署为每个 FactorTester 服务器提供独立 WireGuard 身份；每个已注册节点都能通过私有 overlay 地址访问其他节点，NAT 节点的加密 IP 包可经一个公共 WireGuard 网关转发，但不需要应用层 relay。

客户端仍需要稳定的公共入口，不能获知 WireGuard 地址，也不能连接执行 worktree 端口。PostgreSQL 有独立的 WireGuard/Compose 生命周期，不得成为已授权文件流的依赖。

## 决策

### 四个固定网络面

| 网络面 | 默认端口 | 使用者 | 职责 |
|---|---:|---|---|
| 客户端控制面 | TCP 7998 | Web、Swift、CLI | UI、会话、元数据、调度、短期传输授权 |
| 客户端数据面 | TCP 7997 | Web、Swift、CLI | 经能力授权的上传/下载字节 |
| 对等控制面 | WireGuard 地址上的 TCP 17998 | 仅 FactorTester 节点 | 签名注册、服务代理、不可变 Attempt 上下文和节点 ticket |
| 对等数据面 | WireGuard 地址上的 TCP 17997 | 仅 FactorTester 节点 | 源读取与目标写入 |

公共监听与对等监听使用不同 HTTP handler；客户端路由不能出现在对等端口，对等路由也不能出现在客户端端口。对等监听必须绑定显式私有 WireGuard 地址，拒绝 wildcard、loopback、multicast 和公共地址。

8000、8141 及将来的 Issue worktree 端口仍是其 Manager 后面的 loopback 服务；对等节点通过 17998 控制转发选择它们，不能直接开放。

PostgreSQL 使用独立的 WireGuard 身份和隧道，存储用户、组织、层级、设备、分布式配额和审计投影，不是传输队列，也不承载生成物/提交物字节。FactorTester 和 PostgreSQL 隧道可以独立升级或恢复。

### 端点身份与发现

一个有版本的节点公告包含 `client_control_endpoint`、`client_data_endpoint`、`peer_control_endpoint`、`peer_data_endpoint` 四个端点。不能从公共 URL 推导 peer 端点。协议 v2 用节点已注册 Ed25519 密钥签名完整端点集、节点身份、签发时间、nonce 和过期租约；接收端持久化 nonce/签发状态，发送端在本地 SQLite 持久化严格递增时钟，以防篡改、重放和时钟回拨导致旧心跳覆盖新租约。

引导 URL 必须是私有 WireGuard IP 的 17998，公共 7998 会被拒绝。缺失、过期或无效端点规划 Attempt 时返回 `node_unreachable`，不回退到公共地址、SSH 或 NAT 穿透。Attempt 保存相关端点的不可变快照，拓扑变化创建新 Attempt。

### 持久权威与生命周期

接收客户端请求的 Manager 在本地 `transfers.sqlite` 拥有 Transfer，保存不可变请求、Attempt、端点快照、能力哈希、状态、重试错误、长度和 SHA-256。生命周期为：

```text
created -> planned -> dispatched -> streaming -> verifying -> completed
                                  -> retry_wait -> planned（新 Attempt）
                                  -> failed / expired / cancelled
```

一个幂等键标识一个逻辑请求；失败 Attempt 不改写，重试创建新序号、新路由快照和经过校验的目标恢复偏移。

### 下载

客户端先向 7998 请求某个保留生成物的访问权，得到短期、角色限定 bearer 和所选 Manager 的公共 7997 URL；7997 不接收 Manager 会话 cookie。读取本地生成物时由所选节点从本地持久文件提供；读取远程生成物时由所选节点通过 WireGuard 从存储节点 17997 拉取。支持 `HEAD` 和一个严格 HTTP byte range；源端在服务任何 range 前校验长度和 SHA-256。

### 上传

客户端先向 7998 请求提交权并声明长度和 SHA-256。本地目标由公共 7997 写私有 staging、校验完整对象后原子提升；远程目标由所选节点经 WireGuard 直接写存储节点 17997。只有目标节点拥有 staging 和最终对象；中断上传只保留目标 staging，重试从经过校验的目标偏移继续。

### 授权边界

客户端能力为 `client_download`/`client_upload`；对等能力为 `origin_read`/`destination_write`，并绑定认证的请求所有者节点。所有能力还绑定 Transfer ID、Attempt ID、主体、字节窗口、过期时间和对象身份；持久存储只保存 bearer 哈希。Web、Swift、CLI 和对等传输携带 bearer/节点签名时拒绝重定向，7998 与 7997 同主机时也明确不向数据面发送 Manager cookie。

### 模块边界

当前唯一数据面入口是 `server.manager.data_plane.app`。客户端和对等服务器只共享很小的传输运行时，并使用不同 handler；流式、范围、完整性、生命周期、本地源、直拉、本地目标和直推都是独立语义模块。

旧的 `server.manager.services.artifacts`、HMAC ticket codec、`/v1/artifacts`、服务端口字节路由、ZIP 路由、NAT 命令、SSE 节点 hub/agent、inbox/outbox 命令存储和 relay rendezvous 删除，不作为兼容路径保留。Web、Swift、CLI 统一使用 7998 授权后通过无 cookie 的 7997 传输字节。

## 故障行为

缺失/过期 WG 端点返回 `node_unreachable`；对等控制/数据超时进入重试，不猜端点、不回公共回退；客户端中断使当前 Attempt 失败，新请求或同一幂等键创建重试 Attempt；目标已提交但最终响应丢失时用完整长度重新校验，不重复传输；完整性不匹配不替换最终对象；PostgreSQL 故障不影响现有会话和本地/已知对等传输；数据面重启依靠本地持久请求、Attempt、ticket 哈希和 staging 状态，不依赖内存 rendezvous。

## 后果

所有服务器对使用可预测的应用 overlay；NAT 节点可以让加密 IP 经一个公共网关转发，但没有应用层 NAT 传输模式或每公共服务器一个请求监听器。公共 7998 永不承载生成物/提交物字节。客户端只需 7998 和 7997，17998/17997 是 WireGuard 内部实现细节。跨节点传输需要 WireGuard，overlay 丢失时明确报错而不是降低安全等级。
