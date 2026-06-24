# GTHT 原生客户端（macOS + iOS）

一套 SwiftUI 代码同时构建 macOS 与 iOS App，连接你自托管的 GTHT 服务器。
对应 issue #122「单一实现、多端复用」的原生落地：

- **首页已原生迁移**（`home.html` → `HomeView`），其余模块自动「转发到 web 版本换页」
  （App 内 WKWebView 加载服务器对应路由，复用现有 web 前端）。
- **跨客户端模块注册表**：首页模块来自服务器的 `static/config/modules.json`，
  web 与原生 home 读同一份。新增模块只改这一处，所有端同步出现。
- **用户自填服务器地址**：首次启动进入「配置服务器」，填协议 / 主机 / 端口，
  持久化保存，之后可在右上角菜单「服务器设置」随时修改。
- **自签名证书**：对已配置的那台主机放行自签名 https（URLSession + WKWebView 双通道），
  其余主机仍走系统校验。
- **苹果原生界面**：NavigationStack、Form、系统材质与系统色，自动明暗模式。

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
      Home/                   首页原生迁移
      Auth/                   登录 / 注册、SessionStore
      Settings/               服务器设置
      Web/                    WebPageView（转发到 web 的 WKWebView + cookie 桥接）
  Resources/                  Assets（图标 / 强调色）、entitlements
```

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
open GTHTClient.xcodeproj
```

> `GTHTClient.xcodeproj` 是生成物（已 gitignore）。改了 `project.yml` 后重新 `xcodegen generate`。

## 构建可安装版本

### macOS

1. Xcode 选 scheme `GTHTClient-macOS` → My Mac → Run，或：
   ```
   xcodebuild -project GTHTClient.xcodeproj -scheme GTHTClient-macOS \
     -configuration Release -derivedDataPath build build
   ```
   产物 `.app` 在 `build/Build/Products/Release/GTHTClient.app`，可直接拷给他人运行
   （自签名/无签名时对方首次打开需右键「打开」绕过 Gatekeeper）。

### iOS

- **模拟器**：scheme 选 `GTHTClient-iOS` + 任一模拟器，Run。
- **真机安装**：在 target 的 Signing & Capabilities 里选你的开发者账号（免费 Apple ID 即可做
  7 天自签名调试安装），连上 iPhone 选为目标设备 Run；或 Product → Archive → 导出 ad-hoc / development `.ipa`。
  - `project.yml` 里的 `DEVELOPMENT_TEAM` 留空，请在 Xcode 里选 Team 自动签名，或填入 Team ID 后重新 `xcodegen generate`。

## 首次使用

1. 启动 App → 「配置服务器」填写：协议（http/https）、主机或 IP、端口（如 `8000`）→ 保存。
2. 首页出现模块网格（来自服务器注册表）。点需要登录的模块会弹出登录/注册。
3. 右上角菜单可「服务器设置」改地址、或退出登录。
