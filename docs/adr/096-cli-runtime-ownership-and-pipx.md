# ADR 096: CLI 与测试运行时的环境所有权

> 本 ADR 的终端安装方案已由 [ADR 098](098-app-managed-cli-environment.md)
> 取代。`pipx` 不再是普通 FTClient 用户的安装方式；本文件保留用于
> 说明测试运行时与 CLI 依赖为何分离。

## 状态

已被 ADR-098 取代（保留为历史决策）

## 背景

FactorTester 同时有研究 CLI、Manager CLI、Swift 客户端内置 runtime 和实际
测试执行环境。把 CLI 安装到 `GTHT` 会让用户工具依赖与仓库/服务器依赖混在
一起；把测试包安装到 CLI 环境又会使本机研究工具的升级影响已有测试。

## 决策

1. `factortester` 和 `factortester-manager` 可以继续由同一个发行包发布，使用
   两个独立的 console entrypoint 和命令树。
2. 终端安装使用 `pipx`。它为应用创建独立的虚拟环境并暴露命令；不把 CLI
   安装到 `GTHT`、系统 Python 或其他项目环境。
3. `GTHT` 只负责 FactorTester 仓库开发、服务器调试和测试套件，不声明或
   安装 FactorTester CLI 发行包。
4. Swift App 内保留两个签名 launcher：研究功能使用 `factortester`，Manager
   登录/设置使用 `factortester-manager`。它们是 App 内部 runtime，不依赖
   用户的 Conda/PATH。Research Agent Skill 与该 runtime 同版本发布。
5. Job 的测试依赖由 Docker runner 或独立 native runner 持有，并由 Job 的
   依赖清单/锁定版本选择和复用。CLI 环境不得安装或升级测试依赖。

## 后果

- 普通研究用户不需要理解 Conda 环境；Swift 客户端直接使用内置 runtime。
- 管理员可在没有源码 checkout 的设备上用 `pipx` 安装同一包并运行
  `factortester-manager`。
- `GTHT` 与用户 CLI 升级相互独立，测试环境也不会被 CLI 更新污染。
- 同一 wheel 中仍包含两个入口并不等于研究 CLI 获得 Manager 命令；权限仍由
  entrypoint、服务端会话和服务端角色共同约束。
