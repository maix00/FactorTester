# 原生 wheel 发布

此目录中的历史包不再作为公网构建的输入。使用 `build_nautilus_linux_wheel.sh` 构建，再由 `prepare_nautilus_wheel_for_build.sh` 生成独立的 BuildKit `native-wheels` 上下文；公网发布在切换前验证两份包及其校验和。新编译包不再加入 Git。

## 构建与磁盘预算

- 普通前端/Python 更新不编译 Rust；镜像的 requirements、CLI 工具层与原生 wheel 层独立缓存。
- 同一 Nautilus/alpha/运行时源码与目标平台使用同一成品 wheel；校验和通过后直接复用，不要求先满足完整编译的空闲空间门槛。
- Rust 变更复用同一个受锁保护的 Cargo target；源码同步保留未变文件的 mtime，默认开启增量编译。整个 Job 不在公网应用主机编译。
- 默认 Cargo target 预算为 4 GiB，超出时仅淘汰该脚本拥有的 target；成品 wheel 保留。外部指定的 target 只报告超限，绝不自动删除。容量不足时先明确失败，不挤占系统最后的空间。
- 临时 Git archive 在结束时清除。共享 source/registry 不复制行情数据；部署后仍须按版本保留策略清理旧 wheel/镜像，不做全局 Docker prune，不删除业务数据、数据库或用户备份。
- 日志区分 `cache=hit/miss/stored`、构建身份与总耗时；缓存命中测试不是端到端部署耗时，提速需使用后续真实发布回执衡量。
