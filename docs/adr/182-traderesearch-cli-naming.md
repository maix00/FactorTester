# ADR-182：TradeResearch CLI 的分阶段命名迁移

状态：分阶段迁移。

## 决策

Python distribution 名为 `traderesearch`；唯一安全启动包名为
`traderesearch_cli_bootstrap`。traderesearch/traderesearch-manager 是 canonical
命令，旧 factortester/factortester-manager 暂作同一启动包的别名，没有第二份
CLI实现或行情/因子状态。release wheel构建也按新distribution查找文件。

CLI（含Manager）优先读取 TRADERESEARCH_CONFIG/HOME/STREAM_TIMEOUT/
MANAGER_CONFIG/MANAGER_TOKEN，未定义才读对应FACTORTESTER变量。共用一个
环境读取函数与原配置/cookie/state实现；显式新HOME不会复制或合并旧凭据。
未配置新HOME时保留现有`.factortester`默认目录与Keychain service，避免把
品牌变更变成未经授权的数据迁移。

版本化客户端的稳定命令新增canonical别名，仍指向同一已校验运行时；旧签名
bundle中的物理bin名不改，不复制新的运行时。wheel中的命令都由同一安全
bootstrap启动，继续过滤cwd中的旧checkout覆盖。安装构建验收使用仓库外
临时target，不覆盖当前GTHT的已安装CLI与用户配置。

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

GTHT聚焦CLI配置/HTTP/Manager/启动/安装布局/旧bundle激活与后端能力说明
107项测试通过；未运行全量平台测试。release helper实际构建
`traderesearch-0.1.2-py3-none-any.whl`并在仓库外临时target安装，四个入口
均显示canonical Usage且绕过故意构造的旧checkout污染。回执位于
`/tmp/traderesearch-cli-naming-final-20261027/install-verification.json`。
不包含真实签名macOS应用打包、公网或用户环境升级验收。回退为revert本次
提交并重新构建目标release；没有持久化数据需要恢复。
