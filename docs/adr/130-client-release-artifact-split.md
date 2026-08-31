# ADR-130：FTClient 应用与 Python 运行时发行物拆分

> **编号迁移说明：** 本文原文件名为 `043-client-release-artifact-split.md`。
> 因 ADR-043 已用于交易所式订单生命周期，本文迁移为 ADR-130；决策内容不因重编号改变。

## 状态

已接受。Sparkle 增量步骤已实现；仅应用 payload 与独立运行时发行仍是分阶段
后续工作。

## 背景

Sparkle payload 过去同时包含 `FTClient.app` 和冻结 Python 运行时，Swift 小
改动也会产生约 125MB 的完整 DMG。运行时还包含两个相同的 PyInstaller
二进制：`factortester` 和 `cli-anything-factortester-research`。

## 决策

1. 运行时只保留一个冻结可执行文件；研究命令使用 shell 入口，通过
   `FACTORTESTER_ENTRYPOINT` 选择 Python 模块，receipt 仍需哈希校验。
2. 新安装继续提供完整安装包；已安装运行时的回退路径发布后，Sparkle 再转为
   仅应用 payload。
3. 运行时与 Swift 应用独立版本化；用既有客户端发行密钥签名的 runtime
   manifest 与 channel manifest 并列发布，应用可以激活新运行时而不替换 app。
4. 发行构建区分 `arm64` 和 `x86_64`；Sparkle 选择匹配的 app/runtime，通用
   安装包仅作为兼容回退。
5. Appcast 生成保留上一版本并让 Sparkle 生成 delta。正常发行保留完整 DMG
   用于回滚和首次安装；delta 使用不可变资产路由。Beta `--delta-only` 只发布
   delta，保留私有 `bases/beta/` 作为下一次基线，成功 HTTP 回读后删除新生成
   的完整 DMG，并在指针切换后清理不可达的公共 Beta 资产。

## 后果

第一阶段消除重复的冻结运行时而不改变用户 CLI。仅应用和独立运行时步骤仍需
兼容窗口：Sparkle 不再带 `Contents/Resources/FactorTester` 时，旧客户端必须
能从已激活运行时启动。
