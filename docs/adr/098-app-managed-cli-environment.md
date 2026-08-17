# ADR 098: App 管理 FactorTester CLI 运行时与终端环境入口

## 状态

已接受

## 背景

`factortester` 与 `factortester-manager` 由 FTClient.app 携带并签名。若普通
用户再通过全局 Python、Conda、pipx 或旧版本路径安装一份 CLI，终端和 App
可能执行不同版本，发布更新也无法保证 Manager CLI 与 App 同步。

## 决策

1. FTClient.app 内置并经 receipt 校验的 `factortester`、
   `factortester-manager` 和 Research harness 是普通用户唯一权威运行时。
2. App 激活后在 `~/Library/Application Support/FactorTester/bin/` 生成稳定
   shell launcher。launcher 固定指向当前已激活的、经过校验的版本目录，不能
   依赖系统 Python、Conda 或 pipx。
3. 同一目录生成 `factortester-env.sh`。用户可以 source 它，把
   `FACTORTESTER_CLI`、`FACTORTESTER_MANAGER_CLI`、`FACTORTESTER_CLIENT_ROOT`
   和 App 管理目录加入当前 shell 的环境；环境变量只是调用入口，不改变 App
   的签名运行时选择。
4. 每次安装、更新、修复或回滚后都刷新稳定 launcher 和环境脚本；旧版本
   launcher 不得继续指向已清理的 runtime。
5. `GTHT` Conda 环境只承担仓库开发、构建和测试，不声明 FactorTester CLI
   发行包。发布验证脚本可使用受控构建环境，但不构成终端用户安装方式。

## 后果

- 普通用户只需安装/更新 App，就能同时得到最新的研究 CLI 和 Manager CLI。
- 外部 Agent 可以通过环境脚本调用 App 管理版本，不需要源码 checkout。
- 旧的 pipx/Conda 入口不会被 App 依赖；残留入口应在迁移时清理。
- 开发者若需调试源码，应显式使用仓库模块和 `GTHT` 环境，不应把它注册为
  用户默认 CLI。
