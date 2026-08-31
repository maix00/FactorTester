# ADR 114：公共 Manager Docker 内的 Codex bubblewrap 沙箱

## 状态

已接受，适用于公共 Manager Agent 运行时。

## 背景

公共 Manager 为每个 claimed 研究 Profile 启动一个 Codex `app-server`。Codex 的 Linux `workspace-write` 使用 bubblewrap 的 user/PID namespace。公共容器曾把 bubblewrap 当普通可执行文件安装，同时启用 Docker `no-new-privileges`，导致 Alibaba Cloud 主机上的每条 Agent 命令都停在 `bwrap: No permissions to create new namespace`。

Manager 与 PostgreSQL 是分开的服务。Manager 挂载应用状态和控制面秘密，因此不能为整个容器开启无限制执行；否则 prompt 或工作区负载会成为更大的主机风险。

## 决策

公共 FactorTester 服务采用官方 Codex secure-container 模式：

1. 镜像构建时安装发行版 bubblewrap，并把 `/usr/bin/bwrap` 设为 setuid；
2. 只给 FactorTester 服务该模式所需 capability：`SYS_ADMIN`、`SYS_CHROOT`、`SETUID`、`SETGID`、`SYS_PTRACE`、`NET_ADMIN`、`NET_RAW`；
3. 对该服务禁用 Docker 默认 seccomp 和 AppArmor profile，使 bubblewrap 能创建内层沙箱；
4. 不设置 `privileged: true`，不把这些 capability 给 PostgreSQL，PostgreSQL 继续使用 `no-new-privileges`；
5. 保持 Codex 自身 `workspace-write`、进程内 seccomp 和 `no-new-privs` 约束不变。外层放宽只为创建内层沙箱，不代表 Agent 获得全盘权限。

不增加 FactorTester 传输端口；公共 7998、7997 和 WireGuard UDP 端口仍是唯一发布的应用端口。

## 选择理由

官方 Codex secure Docker profile 记录了这一边界。使用部署公共镜像和该 profile 的临时容器已在目标主机通过 `codex sandbox -- /bin/true`。目标内核拒绝 bubblewrap 新建 `/proc` mount，但当前 Codex sandbox helper 会预检并在没有该 mount 时重试；不启用无限制回退。把 `sandbox_mode` 设成 `danger-full-access` 或设置 `privileged: true` 会移除相关边界，不接受。

## 后果

公共镜像必须保留 `/usr/bin/bwrap` 的 setuid 位。Docker/AppArmor 改动只对 Manager 容器显式生效，PostgreSQL 单独加固。若主机拒绝所需 capability 或 setuid，Agent 沙箱 smoke test 应失败，而不是静默无隔离运行。回滚镜像/Compose revision 会恢复之前的加固容器，但在沙箱先决条件恢复前 Agent shell 仍不可用。

## 参考

- OpenAI Codex secure container profile：<https://github.com/openai/codex/blob/main/.devcontainer/README.md>
- OpenAI Codex Linux sandbox 行为：<https://github.com/openai/codex/blob/main/codex-rs/linux-sandbox/README.md>
