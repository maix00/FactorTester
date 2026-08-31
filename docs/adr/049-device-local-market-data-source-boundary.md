# ADR 049: 设备本地行情源与服务器目录隔离

## 状态

已接受

## 背景

行情源可能属于服务器部署，也可能只存在于某台用户设备。Tiger SDK、账户授权、
实时 L2 连接和本机插件文件属于后一类。如果把本机来源注册到 Manager 或测试服务，
服务器会错误声称自己拥有该来源，普通 Web 客户端也会看到无法访问的产品与能力。
反过来，让浏览器直接读取本机目录既不可行，也破坏了客户端安全边界。

## 决策

1. 服务端 `DataSourceDeclaration` 只表示当前服务器进程实际注册的来源，不接受
   `local/server` origin 选择，也不能投影客户端来源。
2. FTClient 管理的本机来源安装在
   `~/Documents/FactorTester/sources/<source-id>`。每个来源提供严格校验的
   `source.json`；静态目录读取不导入 connector，也不执行网络探测。
3. 普通 Web 页面只请求 `/api/product-library/*`，因此只能看到服务器目录。Swift 内嵌
   页面可以额外请求 `/api/client/product*`；这些请求由 `WKWebView` 消息处理器
   截获，并交给打包的本地 CLI。Manager 不实现这些路由。
4. 本地桥只允许固定的只读目录路径和受限请求体。来源凭证保存在设备 Keychain，
   不进入 manifest、HTTP 请求、服务器数据库或研究报告。
5. Tiger 的目录声明是实时 OSE L2 order-book stream，时间频率为空；不得把市场
   深度写成 `MIN1`、`DAY1` 或其他 K 线频率。可用性与延迟必须由显式本机探测证明。
6. 客户端发布包包含受版本管理的本机来源模板；激活发布包时校验 receipt 与文件
   hash，再原子更新由 FTClient 管理的来源目录。用户自有的其他来源目录不被覆盖。
7. 本机来源模板、发布包和安装目录都不得包含 `__pycache__`、`.pyc`、Finder
   元数据等生成物。构建时过滤，激活时再次拒绝；测试不得通过动态 import 污染发布
   输入目录。

## 后果

- Web 与 Swift 看到不同来源是明确的权限与部署语义，而不是服务器返回后由 UI
  隐藏。
- 服务器无法列举 Tiger，也不知道用户是否安装、授权或正在连接 Tiger。
- 同一套 Web 产品目录仍可复用；只有 Swift 外壳增加本地 CLI transport。
- 本机来源损坏会产生明确错误，不会被静默忽略或回落为服务器来源。
