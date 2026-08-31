# ADR 069：公共主机切换到两个隔离容器

## 状态

已接受。

## 背景

ADR-066 定义本地服务器容器边界和公共主机的两个信任域，但公共主机曾仍以原生系统服务运行 FactorTester 与 PostgreSQL，把 PostgreSQL 以主机 TCP 5432 暴露，并把发布清理耦合到可变主机路径。Issue #184 还要求仅服务器可用、绑定 FactorTester WireGuard 地址的 17998/17997。

## 决策

公共主机只运行 `factortester-public` 和 `postgresql-control` 两个容器。每个容器建立并拥有自己的 WireGuard 接口和 root-only 密钥。应用镜像嵌入一个完整 Git SHA，不运行源码 watcher；PostgreSQL 使用 named volume，并从原生 custom-format dump 做校验恢复。

公共主机只映射 7998、7997、联邦 UDP 51820 和数据库隧道 UDP 51821。主测试端口 8000、PostgreSQL TCP 5432、对等 TCP 17998/17997 不发布到主机；8000 在 FactorTester 容器内仅 loopback，通过 Manager 访问；同主机数据库流量走 Docker 内网；对等监听只绑定容器内 FactorTester WireGuard 地址。

容器启动不依赖 PostgreSQL 健康状态，以便控制库宕机时 Manager、本地任务状态和字节数据面继续服务。依赖数据库的操作返回既有降级错误，恢复后继续。

发布校验器而不是容器 entrypoint 执行幂等控制库 schema 迁移，并检查存储 schema 版本等于应用 revision 声明版本。新的应用通过运行时验证和数据库 restore check 后，才写入已验证部署回执并清理旧应用版本；默认保留三份已验证 revision。清理只允许应用完整 SHA 镜像 tag 和匹配 Git release worktree；PostgreSQL 镜像、volume、备份、无关 Docker 项目和全局 build cache 不在范围内。

可信本地发布器通过本地 2222 维护通道把 `main` 推到公共 bare repository 后执行激活事务；公共主机不从 GitHub 拉取。主机锁串行化发布；传输、构建或验证失败时继续提供已验证版本，重复执行同一命令是幂等重试。

移除原生服务前必须确认容器数据库已有迁移后的 schema/data、自身备份能测试恢复、Manager/data/main 端点通过检查。观察窗口内在 volume 外保留回滚 dump。

## 后果

应用发布只重启 FactorTester，PostgreSQL 保持在线；公共 TCP 5432 和主机级 8000 消失；FactorTester 与数据库对等身份可以独立撤销。旧主机运行时只能在验证后显式删除，不能误删容器数据库 volume。
