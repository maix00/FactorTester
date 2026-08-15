# ADR 085: Swift 客户端由 Web 统一导航，原生层保留平台能力

## 状态

已接受

## 背景

FTClient 同时维护 Swift `NavigationSplitView`/`ClientSidebar` 和 Manager Web
shell。Swift 页面加载 Web 路由时还使用 `presentation=embedded` 隐藏 Web 侧栏，
造成两套主页、模块目录、标签页和刷新行为。客户端更新按钮原本位于 Swift 侧栏，
移除原生导航后也必须保留。

## 决策

1. 已配置服务器的 FTClient 主窗口加载 Manager `/` 的完整 Web shell；Web 负责主页、
   功能入口、侧栏、模块目录和打开的标签页。
2. Swift 不再把 `ClientSidebar` 作为主窗口导航；`WebPageView` 显式区分
   `.standalone` 与 `.embedded`，旧的原生能力页面可以继续使用 embedded 模式。
3. Swift 只保留平台能力边界：服务器初始配置、Keychain/设备认证、自签名证书信任、
   本地 CLI/Adapter、文件选择器、原生 fallback，以及客户端更新。
4. 客户端更新操作迁移到 Web shell 外层原生 toolbar，保留检查、下载、重启安装三种
   单一动作语义；完整更新渠道和签名信息仍在原生客户端设置页中。
5. Web shell 的 `WKWebView` 继续接收 Swift 注入的会话 token/cookie，并在 macOS
   允许已有的本地目录只读桥接；外部 `target=_blank` URL 交给系统默认浏览器。

## 后果

- Web 与 Swift 使用同一套模块权限、主页和标签页，不再需要同步两套主导航。
- 原生更新按钮不会因移除 Swift 侧栏而消失。
- 仍需要逐步把本地 Profile、Adapter 和本地研究能力暴露为明确的 native bridge 或
  client settings 入口；它们不是服务器 Web 路由的权限来源。
- 未配置服务器和无法加载 Web shell 的错误页面仍由 Swift 展示，避免把首次配置锁在
  一个尚未可访问的 Web 页面中。
