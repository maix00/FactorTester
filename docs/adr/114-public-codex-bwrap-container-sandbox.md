# ADR 114：公共 Manager Docker 内的 Codex bubblewrap 沙箱

## 状态

已接受，适用于公共 Manager Agent 运行时。

## 背景

公共 Manager 为每个 claimed 研究 Profile 启动一个 Codex `app-server`。早期方案依赖 Codex 的 Linux `workspace-write` 沙箱；当前运行时改由 `ProfileAgentSandbox` 在 Codex 外层构建每个 Profile 的 Bubblewrap 挂载空间，Codex 在此空间内运行。旧镜像为早期方案给 `/usr/bin/bwrap` 设置 setuid，当前容器中的 Bubblewrap 因而在 Agent 启动时直接报 `setuid use of bubblewrap is not supported`。

Manager 与 PostgreSQL 是分开的服务。Manager 挂载应用状态和控制面秘密，因此不能为整个容器开启无限制执行；否则 prompt 或工作区负载会成为更大的主机风险。

## 决策

公共 FactorTester 服务使用独立的 Profile Bubblewrap 空间：

1. 镜像构建时安装发行版 bubblewrap，明确将 `/usr/bin/bwrap` 设为非 setuid 的 `0755`；`ProfileAgentSandbox` 由非 root 用户启动它；
2. 只给 FactorTester 服务该模式所需 capability：`SYS_ADMIN`、`SYS_CHROOT`、`SETUID`、`SETGID`、`SYS_PTRACE`、`NET_ADMIN`、`NET_RAW`；
3. 对该服务禁用 Docker 默认 seccomp 和 AppArmor profile，使 bubblewrap 能创建内层沙箱；
4. 不设置 `privileged: true`，不把这些 capability 给 PostgreSQL，PostgreSQL 继续使用 `no-new-privileges`；
5. `ProfileAgentSandbox` 只挂载当前 Profile 工作区、必要的系统可执行文件与被选中的 Skill；Codex 配置中的 `danger-full-access` 仅作用于这个已隔离的空间，不代表 Agent 可访问整个 Manager 容器。

不增加 FactorTester 传输端口；公共 7998、7997 和 WireGuard UDP 端口仍是唯一发布的应用端口。

## 选择理由

在目标公网容器中，同一 UID 使用 setuid 的 `/usr/bin/bwrap` 运行 Profile 沙箱命令会立即失败；使用非 setuid 副本则能运行完整命令。实测隔离空间能访问本 Profile 与选中的 Skill，但看不到其他 Profile、容器中的应用源码和 `/etc/shadow`。因此镜像固定非 setuid 模式，保留沙箱失败即拒绝启动的边界；不启用无沙箱回退，也不设置 `privileged: true`。

## 后果

公共镜像必须确保 `/usr/bin/bwrap` 没有 setuid 位。Docker/AppArmor 改动只对 Manager 容器显式生效，PostgreSQL 单独加固。若主机拒绝所需 namespace 或 mount，Agent 沙箱 smoke test 应失败，而不是静默无隔离运行。回滚到带 setuid 位的旧镜像会重新触发 Agent 启动失败。

## 参考

- OpenAI Codex secure container profile：<https://github.com/openai/codex/blob/main/.devcontainer/README.md>
- OpenAI Codex Linux sandbox 行为：<https://github.com/openai/codex/blob/main/codex-rs/linux-sandbox/README.md>
