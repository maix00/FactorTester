# ADR 089：对象字节使用 7997 数据面

## 状态

已接受，按 Issue #216 分阶段实施。

## 背景

账户域同步和对象传输有不同的故障与所有权要求。PostgreSQL 和每个 Manager 的账户 SQLite 保存小型用户元数据、revision 和 outbox；研究报告附件、publication 资产、本地资源快照、因子源码、Job 提交物和 Job 生成物更大，有一个存储所有者，并且 PostgreSQL 不可用时仍应可用。

旧研究 publication 路径把有界对象正文放进 7998 JSON 的 `content_base64`，使元数据读取也携带文件字节，且无法让多个存储 Manager 共用传输协议。

## 决策

使用两条并行但独立的通道：

1. 账户域通道在 Manager 本地 SQLite 镜像保存用户、组织、Profile、因子 manifest、产品分类和 publication 元数据，再与 PostgreSQL 懒同步；它不在字节传输关键路径。
2. 对象通道用 Manager 7998 传递对象身份、元数据、授权、传输记录和短期能力，用 Manager 7997 通过本地或 WireGuard 路由传递经过校验的字节流。
3. 每个传输除旧 Job 字段外还标识不透明的 `object_kind` 和 `object_id`。`ObjectOriginRegistry` 选择领域 Origin Adapter；Job 生成物解析器只作兼容回退。
4. 研究 publication 是两阶段操作：先提交无源码投影，再为每个资产、附件和本地资源取得独立 7998 上传能力并通过 7997 上传。目标 adapter 校验声明大小和 SHA-256，原子提升到 publication 存储目录。
5. 新 publication 客户端不得在 7998 投影中发送对象正文。迁移期间仍接受旧 `content_base64`，但服务器存储前剥离，并不通过联邦读取响应暴露。
6. 存储 Manager 对对象字节负责。远程读取者从 7998 获取元数据，再向请求所有者 Manager 请求 7997 ticket；源 Manager 不可用时明确读取失败，不创建隐式副本，不把字节复制到 PostgreSQL。
7. 因子源码有自己的 `factor_source` 对象类型、Origin Adapter 和 Destination Adapter。发送给候选执行器的 Run context 只带规范族引用、源码策略、字节数、SHA-256 和存储 Manager；能力预检前由源 Manager 经本地 7997 上传端点 staging，目标提交到本地因子源码 SQLite，然后执行器重新加载并校验。直接完整源码 context 只供本地兼容调用方和测试使用。

## 模块边界

```text
server/manager/objects/       # 对象类型、引用、Origin/Destination registry 与 adapter
server/manager/services/      # 研究对象传输、因子源码传输
server/services/              # 因子源码对象 manifest
server/manager/http/          # 7998 对象上传能力路由
tools/cli/.../public_research/ # publication 对象与上传 seam
```

这个模块边界避免 `runtime.py`、`federated_public_data.py` 和数据面入口继续变成存储专用注册表。新增对象族只需新增 Origin/Destination Adapter 和测试，不新增 Manager 间传输协议。

## 后果

PostgreSQL 宕机不阻塞已有本地对象传输；publication 可以先在元数据中列出，字节上传完成前缺失正文明确报告 unavailable，而不是静默通过控制库复制。上传按 publication、对象类型、对象身份和内容哈希独立重试且幂等。远程因子执行在能力预检阶段发现源 Manager 或目标数据面不可用时失败，不把源码文字嵌入 7998 Run 请求。所有 Web、Swift 和 CLI 发布者迁移到对象上传能力后，才能删除旧投影兼容路径。账户域通道与对象通道独立监控和重试，不增加第二个 PostgreSQL 端口或数据库。
