# ADR 093: FactorTester CLI 按 Skill 边界拆分

## 状态

已接受

## 背景

原有的 `factortester` 根命令同时注册研究命令、本地客户端命令、Manager
控制、服务器管理和客户端发布命令。这样研究 Skill 的执行入口携带了不属于
研究任务的运维能力，Swift Manager 页面也只能复用同一个可执行文件和嵌套的
`manager` 命令组。

## 决策

1. `factortester` 是研究/客户端入口，只注册研究、因子/产品目录、Profile、
   报告、Evidence、Job、Run 和本地客户端运行时命令。
2. `factortester-manager` 是独立的 Manager/operator 入口，直接提供
   `configure`、`login`、`status`、`restart-fleet` 等 Manager 命令，并提供
   `admin`、受授权的 Agent budget/invocation 以及 `client release`。
3. `client activate-bundle` 保留为客户端入口中的隐藏命令，因为 Swift 首次
   启动需要用它激活内置运行时；它不出现在普通帮助中，也不授予服务器权限。
4. 两个入口共用同一个发布 wheel 和同一个冻结 Python runtime，但使用两个
   明确的前门：应用包中的 `factortester-manager` 是设置页 Manager UI 的
   专用 launcher；普通研究流程始终调用 `factortester`。
5. Manager 的 Keychain token、普通 FactorTester session、Swift session 和
   设备密钥仍然是不同凭证。CLI 的命令拆分不替代服务端的角色授权。

## 后果

- 研究 Skill 和 CLI-Anything harness 不再需要知道 Manager 的嵌套命令路径。
- Server Maintenance Skill 使用 `factortester-manager`，与研究入口在安装后
  即可区分；Swift Manager UI 不会误调用研究 CLI。
- 应用包需要同时验证和激活 `factortester`、`factortester-manager` 与研究
  harness launcher，因此运行时缓存 schema 从 7 升至 8。
- 旧的 `factortester manager ...`、`factortester client release ...` 路径不再
 作为公开兼容入口；服务器权限和登录流程仍由后端独立校验。
