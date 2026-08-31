# ADR-135：Web 与 Swift 共用语义模块图标契约

> **编号迁移说明：** 本文原文件名为 `067-web-swift-icon-contract.md`。因 ADR-067
> 已用于联邦传输控制面，本文迁移为 ADR-135；决策内容不因重编号改变。

## 状态

已接受，迁移仍按下述分阶段完成。

## 背景

模块注册表由旧 Web 首页和 Swift 客户端共用，模块同时有 `icon` 和 `sfSymbol`。
Swift 用 `Image(systemName:)`，旧 Web 却把 `icon` 当文本，导致服务器模块在
不同表面显示 `OPS`、`server.rack` 等不一致图形。Manager Web 不能加载 SF
Symbols 字体，已有 `server/manager/web/core/icons.js` 的语义 SVG 注册表。

## 决策

1. 跨客户端复用语义身份而不是原生图片；`sfSymbol` 是跨客户端契约，
   `server.rack` 是 `server_operations`、Manager 快捷入口和服务器设置的
   规范符号。保证语义和视觉一致，不要求像素相同。
2. `static/config/modules.json` 是唯一模块注册源；新模块必须提供支持的
   `sfSymbol`。`icon` 只作为旧 Web 的文本/emoji 回退。
3. Web 优先按 `sfSymbol` 从共享 SVG 注册表渲染，旧首页迁移到相同解析器；
   Manager 与旧首页可以有 DOM 适配器，但不能各自硬编码图形。
4. Swift 继续渲染 `Image(systemName: module.sfSymbol)`，仅在符号缺失/不可用时
   使用 `icon`；快捷入口若对应模块，应使用注册表条目。
5. FactorTester launcher/favicon 仍是独立品牌资产契约，不能被 `server.rack`
   替换，Web 不能复制 Swift app icon 或 `Assets.xcassets`。

## 分阶段迁移与验收

先测试 manifest 与 `server.rack` SVG 注册，再把 Web 首页置于共享解析器后，
保持 `/api/modules` 投影同步，最后在旧客户端不再支持后单独版本化移除
`icon` 文本解释。未知符号必须有可访问且确定的回退，不得破坏导航；Web bundle
不得加载 SF Symbols 字体或 Swift 资产目录。
