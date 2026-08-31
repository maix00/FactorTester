# ADR-025：产品路径选择边界

## 状态

已接受。

## 背景

单因子页面曾把前端提交对象当成页面级 `FactorTester`，混淆了三种不同
概念：SQLite 中的用户产品组模板、一次测试选择的产品/路径全集，以及
IC/分组测试运行时的 `FactorTester`。

## 决策

引入 `ProductPathSelection` 表示一次明确的产品/路径选择。它只拥有：

- `selection_id`；
- `selected_paths`；
- `product_group`；
- `manual_selection` 或 `user_product_group_template` 等来源元数据；
- 延迟解析的产品集合。

用户产品组 SQLite 存储中的一行可以通过
`product_group_to_path_selection` 构造一个选择对象。

`ProductPathSelection` 不创建、更新或删除 `FactorTester`。IC 和分组运行器
在运行时根据各自设置创建测试器，并附加本次选择的产品全集元数据；页面级
查询只作为旧前端输入的迁移桥。规范测试 payload 应把
`product_selection` 或 `product_selections` 放在具体测试内。

排序由用户产品组模板存储负责，页面级产品路径选择不实现排序。

## 后果

- 产品分类和收益频率不再作为全局页面覆盖层，而由真正需要它们的测试
  设置模块打开。
- IC 和分组测试保持独立的设置应用；可以共享注册表、基础字段构建器和
  公共 UI，但各模块拥有自己的 tab、默认值、禁用值、chip 和懒加载界面。
- 旧结果/快照 API 可以暂时返回 `submission_id`，但新的产品全集 API 使用
  `product_path_selection_id` 或 `selection_id`。
- `FactorTester` 仍是运行时计算上下文；业务运行器负责创建它，并只在
  结果查询需要时登记测试器。
