# GTHT 原生客户端（macOS + iOS）

一套 SwiftUI 代码同时构建 macOS 与 iOS App，连接你自托管的 GTHT 服务器。
对应 issue #122「单一实现、多端复用」的客户端壳层：

- **完整 Web shell**：已配置服务器后，App 用 WKWebView 加载 Manager `/`，主页、
  功能入口、模块侧栏和打开的标签页全部由 Web 端提供，不再维护一套 Swift 主侧栏。
- **原生能力层**：Swift 继续负责服务器初始配置、Keychain/设备认证、自签名证书信任、
  本地 CLI/Adapter、文件选择器与客户端更新。原生更新按钮位于 Web shell 外层 toolbar，
  不依赖 Web 侧栏是否显示。
- **跨客户端模块注册表**：Web shell 与原生 fallback 都使用 Manager 的 `/api/modules`；
  Manager API 暂时不可用时，原生仅使用最小公共回退目录。
- **用户自填服务器地址**：首次启动进入「配置服务器」，填协议 / 主机 / 端口，
  持久化保存，之后可在右上角菜单「服务器设置」随时修改。
- **自签名证书**：对已配置的那台主机放行自签名 https（URLSession + WKWebView 双通道），
  其余主机仍走系统校验。
- **苹果原生界面**：NavigationStack、Form、系统材质与系统色，自动明暗模式。
- **本地研究界面**：在 App 内启动、停止并用 WKWebView 打开已签名的
  Vibe-Trading 等本地 adapter；外部浏览器仅作为排错备用。
- **版本与身份设置**：查看客户端安装健康状态，管理一个人类 profile 和多个
  provider-neutral Agent profile。密码和 adapter secret 只进入 Keychain。

## 目录结构

```
apple/
  project.yml                 XcodeGen 工程定义（macOS + iOS 两个 target）
  Sources/
    App/                      @main 入口、RootView（按是否配置服务器分流）
    Config/ServerConfig.swift 服务器地址（持久化、可改）
    Networking/               APIClient、自签名信任、数据模型
    Navigation/               Module 模型、ModuleRegistry（共享注册表）、页面解析
    DesignSystem/Theme.swift  统一视觉令牌
    Features/
      Web/                    完整 Manager Web shell 与 WKWebView 桥接
      Auth/                   登录 / 注册、SessionStore
      Settings/               服务器、版本、profile 与 Keychain 设置
      Adapters/               本地 adapter 生命周期与内嵌 Web UI
  Resources/                  Assets（图标 / 强调色）、entitlements
```

## 多语言基础设施

- 所有界面共享 `Resources/Shared/Localizable.xcstrings`，当前提供 `zh-Hans`
  与 `en`。新增语言只需在 String Catalog 中添加一个 localization，语言选择器会
  从 bundle 自动发现，不需要修改功能模块。
- 根场景注入 `LanguageStore`，统一保存 `client.language`、更新 SwiftUI 的
  `Locale`，设置页和服务层都读取同一状态。`L10n.format` 只用于动态格式化文本；
  JSON、状态码、API 字段和研究正文保持原始值。
- 共享设置组件会把设置标题、说明和占位符转换成 `LocalizedStringResource`，避免
  功能页通过 `String` 属性绕过本地化。用户提供的路径、Profile 名称、服务器响应和
  研究报告内容则按原文显示。
- 提交前运行 `./scripts/audit-localization.py`。脚本会检查 SwiftUI 可见文字、
  设置项和页面卡片的命名参数、图表与研究展示分组、`L10n` 动态键、展示辅助函数
  返回的动态文字、重复键和 String Catalog 中每个语言的非空翻译，并拦截高风险的后端状态裸
  显示，逐个输出 App、Account、Jobs、Profiles、Settings 等功能模块的覆盖状态。

## 前置要求

- **完整版 Xcode**（不是 Command Line Tools）。安装后执行一次：
  ```
  sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
  ```
- **XcodeGen**：`brew install xcodegen`

## 生成并打开工程

```
cd apple
xcodegen generate
   open FactorTester-Client.xcodeproj
```

> `FactorTester-Client.xcodeproj` 是生成物（已 gitignore）。改了 `project.yml` 后重新 `xcodegen generate`。

## macOS 测试与工作区授权

macOS hosted tests 和 UI tests 会启动使用 `com.gtht.client` 的应用宿主。
必须通过持久的 `FTClient Beta Release` identity 运行：

```bash
./scripts/test-macos-signed.sh
```

不要为这两类测试传入 `CODE_SIGNING_ALLOWED=NO`。无签名宿主会被 macOS
视为另一个应用，导致已经保存的个人工作区 Documents 授权再次弹出。
测试脚本会在缺少持久 identity 时直接失败，不会降级成 ad-hoc 或无签名宿主。

## 构建可安装版本

### macOS

1. Xcode 选 scheme `FactorTester-Client-macOS` → My Mac → Run，或：
   ```
   xcodebuild -project FactorTester-Client.xcodeproj -scheme FactorTester-Client-macOS \
     -configuration Release -derivedDataPath build build
   ```
   产物 `.app` 在 `build/Build/Products/Release/FTClient.app`。
   正式 Release 继续提供兼容既有更新链的 `FactorTester-Client.dmg`，镜像内为
   `FTClient.app`，拖入 Applications 即可安装。首次运行会在 bundle identity
   一致时安全清理旧的 `FactorTester-Client.app`。
   （自签名/无签名时对方首次打开需右键「打开」绕过 Gatekeeper）。

### iOS

- **模拟器**：scheme 选 `FactorTester-Client-iOS` + 任一模拟器，Run。
- **真机安装**：在 target 的 Signing & Capabilities 里选你的开发者账号（免费 Apple ID 即可做
  7 天自签名调试安装），连上 iPhone 选为目标设备 Run；或 Product → Archive → 导出 ad-hoc / development `.ipa`。
  - `project.yml` 里的 `DEVELOPMENT_TEAM` 留空，请在 Xcode 里选 Team 自动签名，或填入 Team ID 后重新 `xcodegen generate`。

## 首次使用

1. 启动 App → 「配置服务器」填写：协议（http/https）、主机或 IP、端口（如 `8000`）→ 保存。
2. 首页出现模块网格（来自服务器注册表）。点需要登录的模块会弹出登录/注册。
3. 右上角菜单可「服务器设置」改地址、或退出登录。
4. 客户端设置中选择人类或 Agent profile，并配置本地 adapter 的 executable
   路径；secret 由系统 Keychain 保存。
5. 启动 Vibe-Trading 后，其 `127.0.0.1` Web UI 直接嵌入客户端。SwiftUI 不
   硬编码端口，而是读取已验证 adapter contract 返回的 URL。

审批不在设置页面完成。设置页只负责配置和展示已有审批事实；Skill 执行、图变更
和后端更新仍在对应 Agent 对话中接受审计。
