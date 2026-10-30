# ADR-191：主机级 Data-I/O 服务与 Arrow 文件句柄共享

状态：已确定；Nautilus 回放路径正在接入首个实现切片。Manager 图表读取、主机容量准入和跨主机 Arrow Flight 传输仍未完成。

## 决策

同一内核上的 Manager 与多个计算 Worker 使用一个主机级 Data-I/O 服务容器管理
Arrow 列式缓存。服务负责 Parquet 扫描、缓存发布及回收；Worker 不再为 Nautilus
回放自行创建相同缓存条目。数据仍按需分组读取，不把整个数据源保留在服务进程堆内存。

同主机 Unix 热路径通过私有 Unix `SOCK_DGRAM` socket 传递不可变 Arrow IPC 文件句柄。
消费者 mmap 共享卷中的文件；Arrow 字节不经过 HTTP/JSON 或 Python 对象复制。句柄
本身持有打开的 inode，因此读取期间缓存目录淘汰不会让已经打开的文件失效。Worker
关闭 iterator/文件句柄后，操作系统可回收映射页。容器之间共享的是内核页缓存及文件
映射，不是跨进程共享的 Python/Rust 对象。

每个主机/内核域各自部署服务。RunSpec 只固定所需产品、Bar 语义、字段和时间范围；
ExecutionPlan 将输入绑定到具有匹配 Bundle 安装的执行节点。优先把计算调度到数据所在
主机。计算需异地执行时，由来源主机通过 Arrow Flight/gRPC 发送有界 Arrow 批次，并在
接收主机落入本地缓存；不能把 Unix 文件句柄描述为跨主机共享内存。实时行情需另行定义
有序、有背压、可恢复的订阅流，不用历史批量读取 API 逐 Bar 请求。
NautilusTrader 当前官方支持 Linux x86_64/ARM64、macOS ARM64 和 Windows Server 2022
x86_64；这表示 Nautilus 可安装运行，不表示 TradeResearch 的 worker、数据源适配器、
认证和调度包已支持 Windows。当前 execution-node Compose 与 FactorActor 的 Data-I/O
接入只支持 Unix `SCM_RIGHTS` 文件句柄通道。Windows 不支持该通道；Windows 节点需等
Windows worker 包及经实测的同机缓存映射或 Arrow Flight 有界 RecordBatch 传输完成后，
才能报告为可调度能力。Windows Flight 接入未完成，当前不应注册为可执行 Nautilus 节点。

Manager、Worker 与 chart API 可共享同一缓存目录，但仍需各自通过适配器接入服务。
部署容器存在不代表所有消费者已迁移。

## 资源与安全边界

- 复用 `SharedColumnarCache` 的键、不可变 IPC 文件、配额和 producer 锁；不增加第二份
  缓存索引或新的 Job/数据权威。
- 同时请求数、单缓存块、请求帧和每请求块数均有上限。每个 Parquet row group 按
  4096 行分块，避免读取整个 source 文件到堆内存。
- Data-I/O 只接受落在容器配置只读根目录中的真实文件；拒绝符号链接解析后逃逸、
  任意超大列清单、无效 row group 和不受支持的过滤器。
- Unix socket 目录只挂载到被授权的本机服务容器；该接口不取代 Keycloak 的 Manager
  API 身份与对象授权，也不暴露到宿主公网端口。
- Arrow Flight 端点必须 TLS，按 Keycloak 受限服务凭据校验调用者，授权须限制到数据
  安装、产品、字段和时间范围。拒绝把本地文件路径作为远端可调用者控制的通用请求。
- Linux 容器的 RSS 上限不等于共享页缓存上限；主机总容量准入和 Manager/DB/OS 余量
  仍需单独测量。本实现没有生产 RSS、并发吞吐或命中率实测。
- 当前不引入 Ray。现有 Celery/RabbitMQ 继续承担 Job 调度；数据面使用 Arrow IPC/Flight。

## 实施与验收状态

当前 Linux standalone execution-node Compose 启动独立 `data-io` 服务，Unix Worker 通过本地
Unix 数据报 socket 请求缓存文件句柄，Rust Nautilus replay adapter 直接消费这些文件句柄。
开发环境未设置 `TR_DATA_IO_SOCKET_PATH` 时仍允许本地缓存适配，便于单元测试；受管
容器必须设置该路径，且不可在服务不可用时静默回退。

仍需继续接入 Manager 图表读取与其他 Manager/worker Compose；验证同主机多个 worker
并发、服务重启/失败、缓存回收与正在读取的 mmap；再测冷/热缓存的耗时、吞吐和峰值 RSS。
跨主机 Flight 与实时数据流尚未实现；只有在权限、数据修订和背压语义明确后才接通。

## 回退

受管容器移除 `TR_DATA_IO_SOCKET_PATH` 后会使用开发 fallback；正式 Compose 不应在服务
不可用时自动回退。若要回退部署，停止 Worker 后移除 `data-io` 服务，再部署旧容器组。
已有 Arrow IPC 文件均为可重建派生缓存，不迁移、不删除源数据。
