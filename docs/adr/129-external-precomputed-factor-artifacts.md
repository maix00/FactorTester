# ADR-129：外部预计算因子生成物

> **编号迁移说明：** 本文原文件名为 `030-external-precomputed-factor-artifacts.md`。
> 因 ADR-030 已用于外部框架执行桥，本文迁移为 ADR-129；决策内容不因重编号改变。

- **日期**：2026-07-17
- **状态**：已接受；远程注册仍受统一运行/Job API 的版本约束
- **相关**：ADR-022、ADR-025、ADR-030、ADR-141

## 背景

外部研究系统可以生成按日期和产品索引的因子表，但单独的 Parquet 路径不
构成因子契约。FactorTester 还必须保留产品身份、信息时间、执行时间、来源
哈希、缺失值和 Native/隔离框架使用的精确预计算计划。日表使用交易日午夜
索引，而午夜不是可执行的期货事件，夜盘日期也不等于交易日。

## 决策

`PrecomputedFactorArtifact` 是只读、类因子输入：

- 读取前校验交接信息和 Parquet 哈希；
- v1 只接收规范化、无时区的交易日索引；
- 每个外部 symbol 必须明确解析到唯一 GTHT Product；
- 拒绝重复时间/产品、无穷值、全缺失面板、同 K 线执行和未实验的跨市场
  声明；
- 提供向量化 `evaluate()`，不自称 `FactorExpr`，也不支持增量执行；
- 每次运行构造带存在掩码和来源的 `FactorRunResult`；
- 通过市场数据和 `SignalAlign` 产生的真实信号计划映射交易日值。

`FactorSignalStore` 在同一计划键下保存来源，`PrecomputedFactorSource.from_artifact()`
将表和来源带入框架适配器计划。

## 边界

生成物生产者在 GTHT 外部。GTHT 不导入 Vibe-Trading，不执行外部 Python 公式，
也不在未校验时信任生产者标签。生成物的注册、上传/存储策略和冻结 RunSpec
元数据属于独立集成层，不能隐藏在因子加载器中。

## 远程实现状态

当前统一的 `/api/test-authoring/workspaces`、`/api/runs`、`/api/jobs` 提供了运行/Job 生命周期
边界；本 ADR 的外部生成物接入仍需在目标版本中声明相应 source/transfer 能力。
在能力未注册前，Python 层可以使用该边界，但 CLI 不得把未注册的远程能力宣称
为可用。

## 后果

Native 和框架执行可以共享一张已验证的因子表，信号时间保持因果，已有
`FactorExpr` 行为不变。外部生成物不应偷偷扩展作者 API 或绕过冻结运行输入。
