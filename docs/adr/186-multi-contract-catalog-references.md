# ADR-186: 显式多合约 catalog 引用

状态：提议；公共不可变类型已加入并收紧类型/来源身份，源/消费者尚未切换。关联 #447、ADR-184。

## 问题

`LocalCNFutures` 会为请求中的每个合约单独 stage catalog，但当前返回契约是：

```text
dict[product_key] -> {catalog_dir, contract_uid}
```

`stage_catalogs` 使用 `setdefault` 时同一品种只保留第一个合约。即使将来改为
`list`，下游 `strategy_backtest` 仍把输入压成：

```text
inputs: product -> ReplayInput(catalog_dir, contract_uid)
```

因此现在既不能声称完整换月回放，也不能只改源侧返回类型来“修复”。

## 决策（建议）

把 catalog 引用提升为独立、不可变的身份，而不是继续把 catalog 路径塞进
`product -> dict`：

```text
CatalogMemberRef
  authority
  bundle_id
  member_id
  product_ref
  source_product_ref
  contract_uid
  catalog_dir
  bar_type
  source_revision / content identity (可为空，但必须显式)
```

一次 staging 返回：

```text
CatalogSet
  product_ref -> tuple[CatalogMemberRef, ...]
```

约束：

- 每个合约有独立 `contract_uid`、catalog、`bar_type` 和来源 revision；不得按
  `product_key` 静默覆盖。
- 同一品种多合约必须显式保留，调用方决定使用哪一个/哪些；源侧不替执行侧做
  主力切换。
- `product_ref` 仍是平台中立产品身份；contract 是来源成员身份，不能把合约名
  当品种名。
- 允许不同合约的重叠区间和同时交易；拒绝的是同一输入身份的冲突、重复事件或
  缺失生命周期。
- 不新增连续的“伪合约”或按同名合并的 fallback；连续主力是另一个由来源声明的
  产品/成员语义。

## 消费者迁移条件

在执行侧明确以下契约前，源侧保持 fail-closed：

1. Nautilus 回放能否接受同一 product 的多个 `bar_type`；
2. FactorActor 的 `products` 维度如何与多合约行情对应；是否要求连续产品信号或
   独立按合约回放；
3. 换月/重叠区间由谁选择，是否需要在 RunSpec 固定主力规则；
4. report 的 product/instrument 维度如何保留合约 provenance。

在这些条件确认前，`stage_catalogs` 对同一 product 的第二个 contract 直接失败，
而不是返回只含第一个合约的结果。

## 验收草案

- 同品种两个真实合约、允许的重叠区间和一次换月；
- 两个 catalog 的 `contract_uid`、`bar_type`、事件时间、session summary 均保留；
- 消费者能明确选择合约，report 能列出每个合约；
- 缺失/重复/越界请求失败且不写部分 catalog；
- 不读取未请求合约的行情。

## 当前进展

`traderesearch_data.nautilus` 已加入不可变 `CatalogMemberRef` 与 `CatalogSet`：
保留 authority、bundle/member、product/source_product、contract_uid、catalog_dir、
bar_type、可选 source_revision；同 `(source_product_ref, contract_uid, bar_type)`
重复引用会失败。当前 staging 和消费者仍未返回/使用 `CatalogSet`，因此多合约路径
仍是 fail-closed。

本 ADR 不改变当前 `product -> ReplayInput` 兼容路径；该路径在多合约能力落地前
继续 fail-closed。
