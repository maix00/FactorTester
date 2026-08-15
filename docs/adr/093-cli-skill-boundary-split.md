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
2. `factortester-manager` 是独立的 FactorTester application/operator 入口，
   提供 `configure`、`login`、`status`、`server inspect/access`、`jobs`、
   `artifacts`、`storage`、`research-graph` 和 Manager-owned `services`。
   它不提供 host restart、Docker、WireGuard、SSH、发布传输或其他服务器
   管理命令；服务器可以通过自身 `.settings` 声明只读的
   `management_access` 元数据，CLI 负责展示，不负责执行或推断。
3. `client activate-bundle` 保留为客户端入口中的隐藏命令，因为 Swift 首次
   启动需要用它激活内置运行时；它不出现在普通帮助中，也不授予服务器权限。
4. 两个入口共用同一个发布 wheel 和同一个冻结 Python runtime，但使用两个
   明确的前门：应用包中的 `factortester-manager` 是设置页 Manager UI 的
   专用 launcher；普通研究流程始终调用 `factortester`。
5. Manager 的 Keychain token、普通 FactorTester session、Swift session 和
   设备密钥仍然是不同凭证。CLI 的命令拆分不替代服务端的角色授权。

## 后果

- 研究 Skill 和 CLI-Anything harness 不再需要知道 Manager 的嵌套命令路径。
- Server Maintenance Skill 使用 `factortester-manager` 读取服务器声明，与
  研究入口在安装后即可区分；Swift Manager UI 不会误调用研究 CLI。Skill
  可以随管理员专用 Manager 发行包安装，但不进入普通研究 CLI、Swift
  客户端或公开运行时。
- 应用包需要同时验证和激活 `factortester`、`factortester-manager` 与研究
  harness launcher，因此运行时缓存 schema 从 7 升至 8。
- 旧的 `factortester manager ...` 路径以及 Manager 中的服务器级旧命令不再
 作为公开兼容入口；`factortester-manager client release ...` 保留为客户端
 发行入口。服务器权限和登录流程仍由后端独立校验。
