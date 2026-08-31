# ADR 067：联邦传输的控制面与数据面

## 状态

已由 ADR-068 于 2026-08-13 取代。本 ADR 的 NAT/SSE 中继设计从未成为最终生产传输协议。

## 背景

生成物只保留在执行 Job 的服务器。公共 Manager 通常可以互相访问，但 NAT 后的 feature server 只能出站，不能接受公共 Manager 入站。ADR-065 曾通过 SSH 反向隧道（例如 17997）暴露私有 7997，这虽然可运维，却把 SSH 和每节点一个隧道端口变成了应用协议。

只用共享 PostgreSQL 传输队列可以去掉隧道，却会让每次跨节点下载/上传依赖控制数据库，违背“数据库暂时不可用时，已认证用户仍能在在线节点间传输已有文件”的要求。多个公共 Manager 还带来两个独立的所有权：持有私有节点出站控制连接的 Manager 不一定是向客户端提供 7997 的 Manager；持久请求可以在 Manager 间转移，但活动 SSE 或字节流不能无损转移。

## 历史决策

### 持久化权威

接收客户端请求的 Manager 是 `request_owner`。它用 WAL 在自己的 `transfers.sqlite` 中原子写入 Transfer 和第一条 outbox 投递意图；该本地行是请求和重试历史的权威。PostgreSQL 只保存可重建的全局索引与审计副本。`LISTEN/NOTIFY` 只能唤醒 Manager，不能成为持久队列，也不是启动/恢复传输的必要条件。

每个跨 Manager 命令都有稳定幂等键。请求所有者重试事务 outbox，直到目标 Manager 确认；接收方先持久化 inbox key 再确认。审计事件走独立本地 outbox，数据库恢复后再复制。

### 节点控制通道

私有节点在每个控制域只与一个健康公共 Manager 保持出站 SSE 控制连接。SSE 只是唤醒和命令通道，不传文件字节；持久命令序列和 `Last-Event-ID` 支持断线重放，SSE 不可用时使用幂等 ACK 和有界 long-poll。

集群注册凭据只用于首次入网。节点自行生成签名密钥，后续挑战签名绑定已保存的节点身份。请求参数不能选择认证的 `server_id`；节点只接收 `source_server_id` 或 `destination_server_id` 等于自身身份的命令。

### 传输所有权与规划

每个 Transfer Attempt 在传输字节前固定 `request_owner_manager_id`、`relay_owner_manager_id`、`connection_owner_manager_id`、源/目标/存储服务器身份、传输模式和一次跳转预算。规划器依据已认证且会过期的可达性观察选择本地读取、直接拉取/推送、源主动推送、目标主动拉取或明确的 `node-unreachable` 失败；公共客户端永远使用所选 Manager 的 7997，不能被重定向到私有节点或其他节点 loopback。

### 数据面

7998 承载元数据、命令、状态、节点在线信息和短期能力；提交物及生成物字节只走 7997。生产者、消费者和本地源 ticket 分开，并绑定 transfer/attempt、主体、节点、长度、SHA-256、范围和过期时间；持久存储只保存 ticket 哈希。

公共 relay 不持久化文件，只按 transfer/attempt 配对一方生产者和一方消费者，使用有界缓冲和背压；节点校验长度与哈希后原子提升。relay 崩溃会终止 Attempt，客户端以新 Attempt 和经过校验的 Range/offset 恢复；活动 socket 不能声称无损故障转移。

### PostgreSQL 故障

本地传输、已知节点间传输、现有会话、本地身份缓存和 outbox 重试继续工作；需要全局权威的新节点注册及控制数据变更暂停。全局传输索引和审计事件留在本地 outbox，异步追赶。没有或过期的节点在线记录必须明确报离线错误，不能猜端点。

## 模块布局（历史方案）

实现使用语义模块，而不是继续增大联邦、控制数据库、Job proxy 和生成物文件：

```text
server/manager/
  transfers/       # 模型、状态机、规划、协调、节点控制与安全
  storage/         # transfers 本地仓库、outbox/inbox、控制库 adapter
  data_plane/      # 7997 入口、源/中继/流式/范围/完整性
  federation/      # 注册、网关、公告、同步和传输
  http/            # jobs 与 federation 路由
```

`server.manager.app` 仍是 7998 入口。新模块接管全部调用方后，旧实现删除，不保留重复兼容路径。

## 传输状态

```text
created -> planned -> dispatched
                   -> waiting_producer / waiting_consumer
                   -> streaming -> verifying -> completed
                   -> retry_wait -> planned（新 Attempt）
                   -> failed / expired / cancelled
```

只接受声明的状态转换；重复命令返回既有记录；拓扑变化创建新 Attempt，活动 Attempt 不能中途从直连改成推送/拉取。

## 迁移与移除条件

在 ADR-065 仍运行期间，先建立本地仓库/outbox/inbox/状态机和特征测试，再加入节点身份、在线状态、SSE/ACK/重放/long-poll，随后实现本地及直连 7997、源推送、目标拉取，迁移 Web/Swift/CLI 的大文件路径到 7997 流式传输。完成数据库故障、通知丢失、断线、relay 崩溃、恢复、完整性、授权和多公共 Manager 验证后，停止公布 17997、删除生成物反向隧道和 7998 大文件回退；控制回调全部使用原生节点通道后，再把 17998 从正常运行中移除。SSH 保留为运维工具。

## 历史后果

PostgreSQL 故障不阻塞已有生成物传输；私有节点只需一条持久出站控制连接。文件只有一个持久所有者，重试和恢复是显式 Attempt，不是隐藏的 socket 故障转移。当前生产实现以 ADR-068 为准。
