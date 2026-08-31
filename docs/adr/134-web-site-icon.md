# ADR-134：Web 表面共用一个站点图标

> **编号迁移说明：** 本文原文件名为 `067-web-site-icon.md`。因 ADR-067 已用于
> 联邦传输控制面，本文迁移为 ADR-134；决策内容不因重编号改变。

## 状态

已接受。

## 背景

Flask 服务和 Manager Web shell 是不同 HTTP 表面，过去没有向浏览器提供统一的
FactorTester 站点身份。模块 manifest/card 图标不是 favicon 契约，原生
AppIcon 也不是浏览器依赖。

## 决策

1. 保留轻量独立的 `static/favicon.svg` 作为 Web 站点身份，不加载原生图片、
   SF Symbols、字体或模块元数据。
2. Flask 和 Manager 都以 `/favicon.svg` 及浏览器兼容路径 `/favicon.ico` 提供
   同一字节。
3. 旧首页和 Manager shell 显式声明 `rel="icon"`；其他页面可以使用兼容路径。
4. 模块 card 图标、`sfSymbol`、模块 manifest 和 Swift AppIcon 仍是独立契约。

## 验收

契约测试比较两个 endpoint 与检入的 SVG，并确认两个 Web 入口文档声明站点图标。
