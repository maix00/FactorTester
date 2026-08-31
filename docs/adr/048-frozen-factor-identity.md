# ADR-048: 冻结因子身份与运行时名称

> **当前入口说明：** 本文的冻结身份决策仍有效；下方 CLI 片段保留为历史来源示例，不代表当前公开命令树。
> 当前因子库 API、CLI 和内部目录迁移边界见 [ADR-141：业务 API、CLI 与内部实现目录的分域迁移](141-api-cli-and-implementation-layout-migration.md)。

## 状态

历史冻结身份决策仍有效；本文关于运行时引用版本和 RunSpec 表示的部分已由
[ADR-118：因子引用与语义 RunSpec v3 顺序](118-factor-ref-runspec-v3.md) 取代。
当前可执行对象使用 `factor:v2`、`factor-family:v2` 和 `factor-set:v2`；`v1`
只用于历史输入、迁移工具和回归夹具，不得用于新的 RunSpec。

## 决策

因子 alias 只描述因子家族与参数，不是持久对象身份。一次 IC、回测、
EvidenceUse 或 Trial 必须先将 owner、Git commit 和完整 alias 解析为不可变的
`factor:v2` 引用。`factor-family:v2` 只用于因子家族页面和报告导航，不能成为
可执行研究 subject；多个具体因子使用 `factor-set:v2`。

owner 与 family 是两个字段。`profile:maxa:MmRateOfChg` 表示 owner
`profile:maxa` 下的家族 `MmRateOfChg`，而 `profile:maxa` 只是 owner，不能被
推断成家族。公共 owner 的规范名称是 `public`；新引用不得输出 `$COMMON`。

Profile 的因子仓库由其注册信息唯一确定，用户不得再选择另一个工作区。普通
用户省略 source settings 时，使用当前用户的个人因子仓库和最新已提交版本。
显式选择 Git commit 时只读取该 commit；其中不存在所选 alias 时必须失败，
不得回退到更早提交。

冻结对象进入因子引擎后，`Factor.name` 使用 `factor_ref`，
`FactorFamily.name` 使用 `family_ref`，alias 保持原样。owner 作为
`owner_ref` 显式保存，不从 `name` 拆解。尚未冻结的交互式对象使用明确的
`runtime-factor` 身份；其可变计算结果仍属于单次运行状态，不进入冻结引用。

## 对象关系

```text
owner_ref + repository + Git commit + factor alias
                        |
                        +-- factor-family:v2  (导航对象)
                        +-- factor:v2         (可执行对象)

factor:v2[] + frozen manifest
                        |
                        +-- factor-set:v2     (可执行对象集合)
```

Workspace 只提供可变配置和仓库 provenance，不声明或限制研究对象。Work
Package/Branch 可以随研究进展使用不同的冻结 factor 或 factor-set；初始
Workspace 中出现过的 family/alias 不得成为后续提交门禁。

## 历史 CLI 示例（非当前公开命令）

```bash
factortester client profile factor-worktree reference maxa \
  --source-file public_factors/MmRateOfChg.py \
  --identity 'MmRateOfChg|N:20d|$F:1d' \
  --object-kind factor \
  --revision <commit> \
  --json
```

省略 `--git-commit` 使用该仓库 HEAD。省略 `--owner-ref` 时解析当前登录用户；
CLI 会话暂未登录时，只能在本地 Profile 注册表恰好对应一个 principal 时使用
该 principal，否则拒绝猜测。

上述 `client profile factor-worktree reference` 仅用于记录早期“Profile 工作区引用”实现；当前公开
入口不再注册 `factor-worktree`，而使用 `factortester factor-library` 的领域命令和统一的因子引用协议。
`factor-worktree` 目录及其物化 helper 仍被现有服务器/客户端内部实现使用，待 ADR-141 所述的一次性
包名、注册键、能力标识、逻辑路径和测试迁移完成后再清理。
