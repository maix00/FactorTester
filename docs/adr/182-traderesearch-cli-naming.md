# ADR-182：TradeResearch CLI 命名迁移

状态：CLI 命令与用户指引迁移完成；发行运行时仅保留读取旧版签名 bundle 的内部兼容。

## 决策

Python distribution 名为 `traderesearch`；唯一安全启动包名为
`traderesearch_cli_bootstrap`。公开命令仅为 `traderesearch` 和
`traderesearch-manager`；wheel 与新的稳定启动器不再安装旧命令别名。
稳定启动器会在已有且已校验的旧版客户端 runtime 中查找旧物理文件名，确保
升级后仍可启动旧签名 runtime。激活新版本时，只删除内容与旧生成器完全一致的
旧别名和旧环境脚本；遇到用户自有同名文件会拒绝覆盖或删除。

CLI（含Manager）优先读取 TRADERESEARCH_CONFIG/HOME/STREAM_TIMEOUT/
MANAGER_CONFIG/MANAGER_TOKEN，未定义才读对应FACTORTESTER变量。共用一个
环境读取函数与原配置/cookie/state实现；显式新HOME不会复制或合并旧凭据。
未配置新HOME时保留现有`.factortester`默认目录与Keychain service，避免把
品牌变更变成未经授权的数据迁移。

新构建的客户端 bundle 和 wheel 只包含 TradeResearch 命令名；稳定启动器优先
使用新物理文件名，仅为已有且校验通过的旧签名 bundle 回退读取旧物理文件名，
不复制第二份 runtime。wheel 中的命令由同一安全 bootstrap 启动，继续过滤 cwd
中的旧 checkout 覆盖。安装构建验收使用仓库外临时 target，不覆盖当前 GTHT
的已安装 CLI 与用户配置。

## 当前边界与剩余项

后端Nautilus能力说明与CLI帮助/错误使用TradeResearch。前端由#444负责，
本次不修改；GitHub仓库名、签名发布ID、队列/协议头、Catalog收据、托管标记、
持久化路径与历史冻结身份没有批量替换。其迁移要分别处理已有消费者和数据。
这不意味着全部FactorTester符号已清零；领域类FactorTester也不因品牌变更
直接改名。

pip把新旧distribution视作两个包，不能把新wheel简单叠装在含旧distribution的
共享site-packages里，否则共同tools.cli/命令可能互相覆盖。正式升级应使用
已有版本化独立release target切换；独立用户环境应先移除旧distribution后
装新wheel。此次没有执行用户环境卸载、发布或部署。

另见[因子Rust入口审计](../audits/alpha-rust-entrypoints-2026-10-27.md)，其中未完成
的计算迁移/共享/容量验收不由命名改动解决。

## 验证

GTHT 聚焦 CLI、Skill 命名与发行运行时测试 123 项通过；`ClientCLIResolution.swift`
通过 Swift 类型检查；未运行全量平台测试。测试覆盖新 wheel/bundle 只生成
canonical 命令、旧生成别名的安全清理、旧签名 bundle 兼容读取，以及拒绝删除
用户自有同名文件时不推进版本指针。不包含真实签名 macOS 应用打包、公网或用户
环境升级验收。回退为 revert 本次提交并重新构建目标 release；没有持久化数据
需要恢复。
