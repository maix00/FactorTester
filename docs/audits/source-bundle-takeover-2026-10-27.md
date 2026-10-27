# Bundle 接手与简化边界 — 2026-10-27

基线 c6cf88122，#447；此次不修改共享工作区未提交的执行/Rust 文件，不部署或迁移。

## 官方资料与判断范围

- [中金所2025结算细则](https://www.cffex.com.cn/u/cms/www/202501/071747590uho.pdf)
- [郑商所2024结算管理办法](https://www.czce.com.cn/cn/uploadfile/2024/12/06/20241206092335583.pdf)
- [上期所2026风险控制管理办法](https://www.shfe.cn/regulation/exchangerules/otherrules/202606/t20260622_832192.html)
- [INE2026结算细则](https://www.shfe.cn/regulation/ineregulation/businessmethods/settlement/202606/t20260622_832188.html)
- [Nautilus accounting](https://nautilustrader.io/docs/latest/concepts/accounting/)

所核查规则区分交易保证金与结算准备金，前者是持仓占用、后者是未占用的结算资金；
它们不能分别解释为 initial/maintenance。不能据此断言所有券商、所有产品或所有历史日期
均没有单独保证金标准。Nautilus 两个字段是模型输入，不强制源数据存在两个同名原始列。
用户已确认：Bundle 直接提供 Nautilus 字段，不增加 bridge 语义映射。

## 本次修改与限制

LocalCNFutures 统一交易保证金率直接设置 margin_init/margin_maint；删除对原始
initial_margin_ratio/maintenance_margin_ratio 的强制要求。保留有限、非负、缺失与
多空差异校验。测试使用真实 Nautilus FuturesContract 构造验证结果，未跑真实策略 Job。
这里的 source 字段仍来自旧快照读取器，历史生效规则接线未因本次赋值修正而完成。

## 精简后的后续路径

1. 平台：JSON 元信息、权限、产品目录和 UI；执行字段由 Bundle 提供，避免平台再算一次。
2. 执行：保留已有 Rust run_catalogs；Bundle 提供 Nautilus 可读目录/原生适配器。
   准备源数据与原生回放分开测量；不把 Python 逐条转换误称 Rust 原生源读取。
3. 多合约仅保留明确来源的 CatalogSet；多个 Instrument/BarType 共享时间调度，不以
   品种键覆盖输入。因子连续序列选择和策略换月明确区分，不生成新撮合框架。
4. RunSpec 复用已有配置冻结机制记录选择及每次运行的实际来源；不把只覆盖清单的哈希
   当成数据/接入代码内容冻结，也不为平台目录新增数据复制流程。
5. 接入已有结算事件实现；不要把 receipt 观测记录变成第二个 DMTM 账务路径。

当前不能宣称完整 Bundle 独立安装、平台所有字段补全、历史保证金/多合约/实时源全部接通。
