# ADR 015：显式因子作者 SDK 与仓库边界

## 状态

已接受。

## 背景

因子工作区桩文件过去会从 `@factor_workspace`、`__factor_workspace__` 和受保护的 `FACTOR_WORKSPACE` 导入递归跟随实现依赖。因此内部运行时类型会意外暴露给作者，生成的导入可能指向不存在的桩文件，公共接口也会随着实现导入变化。工作区 Git 行为同样分散在构造、同步、钩子和自动同步脚本中；生成的钩子还会捕获当时的 Issue worktree 路径，worktree 删除后就失效。

## 决策

- `tools.data.factor_workspace.sdk` 是生成作者 SDK 的唯一模块级白名单。
- `@factor_workspace` 只在允许的源模块内选择作者可见的符号和方法，不会因为导入关系把其他模块拉入 SDK。
- `__factor_workspace__` 只表示允许模块内导出的单例值；运行时导入不定义 SDK 表面。
- 生成的桩文件不包含作者装饰器及其扫描基础设施。
- `FactorWorkspaceRepository` 负责初始化、分支选择、提交、分支物化、状态、HEAD 查询以及下载到上传的合并。
- 钩子指向稳定的共享 `feat` 根目录，而不是生成钩子时碰巧使用的 worktree。
- 分支物化后刷新 manifest，使选择的分支与实际仓库状态一致。

## 后果

增加作者 API 必须显式修改 SDK 合约并更新生成物测试，这是有意保留的审查门槛。运行时重构不会再意外扩大作者工作区；同时，算子方法签名仍可通过 `@factor_workspace` 与实现放在一起维护。
