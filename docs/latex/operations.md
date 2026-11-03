## 服务部署 {#deployment}

Manager、计算工作端、数据 I/O、Keycloak、消息队列与数据库按职责部署。
同主机的 Manager 与计算、数据服务可以组合安装；远端主机也可以只提供计算或数据。
桌面本机运行时由用户使用，不自动加入 Manager 的远端调度池。

部署输入是已审核的 Git revision、固定 submodule revision、运行时构建身份和保护配置。
源码、原生 wheel、Python 依赖与前端静态资源分别缓存；相同构建按身份及校验和复用。
Rust 构建复用有容量限制的 Cargo 缓存，不在业务服务器上临时编译大型运行时。
Python 依赖未变化时复用依赖快照，不因普通源码更新重新下载一遍依赖。
本机镜像可复用已核对 Python ABI 与依赖版本的固定基础镜像；alpha 独立安装，
始终使用本次固定源码构建的 wheel。构建上下文排除各层目录中的编译缓存和本机动态库。
产物传输按内容校验分块，连接中断后复用已校验块，完整校验通过后才发布。

公网发布可分为准备和激活两阶段。准备阶段传输缺少的产物、检查校验和、建立固定源码
并构建新镜像，保持原应用和生产配置运行。激活阶段重新核对当前版本，制作备份，
在受控窗口切换配置和应用，再检查运行版本、健康及数据库恢复能力。
准备成功不等于应用已激活，也不证明历史数据已满足新版本的条件。

部署工具为 `scripts/server/publish_public_main.sh`、
`scripts/server/activate_public_revision.sh` 和相应容器管理入口。
公网发布需要明确授权以及已同步的 feat/main 包含关系；工作区有未提交修改时拒绝发布。
主机地址、凭据和具体变更参数由受保护的部署配置提供，不写进项目手册或版本库。

## 健康检查与容量 {#health-capacity}

容器健康、应用 HTTP 可达、Keycloak 登录与对象授权分别检查。Manager 可达不代表计算
节点已注册；计算节点在线也不代表它具有任务所需的 Bundle、数据修订和运行能力。
任务验收应沿客户端、Manager、队列、执行节点、生成物读取的真实链路进行。

计算和数据服务配置 CPU、内存及进程限制。数据读取按范围和批次执行，缓存设容量及
生命周期；不同进程共享同一文件的系统页缓存，不把各自的 Python/Nautilus 对象视为
物理共享内存。跨主机请求传输有限范围的数据或结果，不默认复制整份数据到 Manager。

维护时观察进程与容器峰值内存、宿主可用内存、磁盘余量、I/O、队列积压和失败类别。
资源不足先限制并发、批次和缓存，不通过隐藏失败或静默缩小测试范围解决。
原生 wheel、镜像和编译缓存按构建身份与保留策略清理；当前运行版本和必要回退版本
保持可用，避免无差别清空活跃缓存造成每次全量重建。

## 备份与恢复 {#backup-restore}

PostgreSQL 使用一致性备份，SQLite 使用原生备份机制，CouchDB 文档、附件及版本状态
按其存储机制保存。凭据、TLS 信任和部署配置单独保护；不将浏览器 cookie 当作运维凭据。
备份记录校验和、来源版本与范围，在隔离环境实际恢复后再作为可用回退对象。

恢复核对对象引用集合、依赖、行数及内容摘要；同样数量不能证明内容一致。
身份与权限还需比较保留用户的允许及拒绝集合，验证撤权不会被同步、缓存或重试恢复。
恢复后检查当前运行版本和实际请求路径，而不是只根据 Git push 或容器启动成功判定完成。

## 授权与回退 {#authorization-rollback}

常驻 Manager 仅持有其正常业务需要的服务权限。需要额外权限的维护使用独立、临时的
运维进程；不为执行一次维护将常驻服务提升为 Keycloak realm-admin。
用户会话、CLI 会话、节点证明和主机 SSH 凭据保持各自用途，不能互相代用。

回退同时考虑应用镜像、配置、原生运行时和受影响的数据。出现失败时先停止有风险的
写入，核对变更后是否已有其他有效更新，再恢复经过验证的配置与数据；不能覆盖后续
用户操作。授权策略仍引用的 Keycloak provider 必须保持加载，只有先撤回其策略引用
后才能移除 provider。

具体服务器的变更计划、逐对象映射、执行回执与异常记录单独归档。
它们是一次操作的证据，不是项目功能或通用运维方法，不编入本 PDF。


## 增量构建与存储预算 {#incremental-build-storage}

成品 wheel 缓存与 Cargo 编译缓存分别管理。源码及平台身份一致、校验和有效的成品直接复用；只修改 Nautilus adapter 时，独立 alpha Python wheel 只有在其余输入树完全一致且旧字节校验通过后才复用。组合运行时仍须重新链接以包含 adapter 修复，不能给旧二进制改标签冒充新版本。

保留与目标平台、工具链匹配的 Cargo target、registry 和 git 缓存，在不同发布 worktree 间显式使用同一 `NAUTILUS_CACHE`、`NAUTILUS_TARGET_CACHE` 与 `NAUTILUS_WHEEL_DIR`。共用缓存由现有构建锁串行保护；macOS arm64 缓存不能代替 Linux amd64 缓存。默认 `NAUTILUS_INCREMENTAL_ONLY=1`，在缺少 Linux Nautilus 依赖产物时拒绝冷构建；只有明确批准的初始构建才设置为 `0`，以后恢复默认。缓存存在时仍由 Cargo 校验依赖是否有效。

构建前核对可用磁盘及单次峰值预算。现有原生 target 缓存默认预算为 6 GiB；成品与临时源快照另行计量。校验通过的重复 wheel 优先使用同文件系统硬链接；不为每个 worktree 长期复制一套依赖。清理必须按明确产物和保留策略执行，保留当前运行、回退和正在使用的产物；不得清空整个 DerivedData、Docker 卷或用户目录来腾空间。

服务器、macOS 客户端及 iOS 客户端分别选择构建、安装与发布阶段。服务端部署默认不构建或安装客户端；仅有服务端变更时不重打客户端包。客户端构建复用现有 Xcode DerivedData，清理是显式操作；安装前另核对目标设备、签名和实际产物。iOS 模拟器与真机产物、安装与分发不可混为同一阶段。


### 可选客户端发布阶段 {#optional-client-stages}

统一计划入口为 `python -m scripts.release.deploy`。默认只输出 JSON 计划，不执行服务器变更、客户端构建或安装；使用 `--execute` 才执行选中的阶段。阶段顺序执行，失败后停止后续阶段。服务器发布仍复用原有脚本、授权、备份与验收门槛，不另建发布协议。

```bash
# 仅审查桌面与模拟器构建计划，不安装或启动 App
python -m scripts.release.deploy --macos build --ios build

# 明确选择执行 macOS 构建，保留运行中的 App
python -m scripts.release.deploy --macos build --max-client-cache-gib <agreed-gib> --execute

# 为已经启动的指定模拟器构建并安装，不自动启动设备
python -m scripts.release.deploy --ios install --device-id <simulator-udid> --max-client-cache-gib <agreed-gib> --execute
```

`--server public` 必须在干净 main worktree 中执行并具有既有发布授权；`--server intranet` 必须在干净 feat worktree 中指定 `--intranet-env`，只重载所选 Manager，不重启整套服务。两者默认均不安装客户端。macOS 安装使用 `--macos install`，沿用稳定签名、暂存校验和原子替换；只有进入安装阶段才退出已有 App。iOS 真机安装还须使用 `--ios-target device`、明确设备及有效 `--team-id`，不自动请求或扩展签名权限。当前入口不上传 App Store/TestFlight，也不创建移动分发授权。

客户端构建默认复用各平台的 DerivedData，不执行 clean。macOS 的历史 Debug 目录清理改为显式设置 `FTCLIENT_DEBUG_CLEANUP=1` 才启用；构建失败不通过删除缓存重试。计划入口默认要求至少 15 GiB 可用空间，执行客户端构建或安装前，必须显式指定三个客户端构建目录的合计预算 `--max-client-cache-gib`，不默认批准数 GiB 的本机新增占用。检查发生在执行前和每个阶段结束后；它是停止后续步骤的门槛，不是操作系统硬磁盘配额。超限时保留产物并报告，不擅自删除缓存或已安装 App。
