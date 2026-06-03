# FactorTester — Agent Configuration

## Agent skills

- **Issue tracker**: GitHub Issues — `gh` CLI against `maix00/FactorTester`. See `docs/agents/issue-tracker.md`.
- **Triage labels**: Default — `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.
- **Domain docs**: Single-context — one `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.

## “被分配 Issue 号即可开工”的总流程（并行友好 / 多 Agent）

> 目标：人类只需要对 agent 说一句“你负责 Issue #N”，agent 就能自行判断能否开工、如何隔离并行、做完如何回到 `feat`，以及什么时候由人类合入 `master`。

### 0. 现成解决方案（为什么这样设计）

并行协作里最稳定的一套组合是：

1. **一任务一分支 + 一任务一工作区**：用 `git worktree` 为每个任务创建独立目录，减少互相污染（每个 worktree 有自己的 `HEAD`/`index` 等元数据）。citeturn1search1turn1search4  
2. **显式 Claim（认领）机制**：用 Issue comment / assignee 表示“谁在做”，避免重复劳动；GitHub 本身也支持把 Issue assign 给某个用户。citeturn1search2turn1search7  
3. **Ownership（写入范围）**：每个 Issue 明确允许修改的目录/文件；更强约束可用 `CODEOWNERS` 来表达代码归属/审阅责任。citeturn1search0turn1search5  
4. **顺序集成（单点 merge）**：并行开发，顺序合入，降低冲突放大。

本仓默认采用：**worktree 隔离 + Issue claim + Ownership + 人类顺序 merge**。

### 1. Agent 接到任务时的自检（必须做）

当人类分配你一个 Issue 号 `#N` 后，你必须按以下顺序自检：

1. **读取 Issue**（没有 Issue body / 验收标准就不要动手）
   ```bash
   gh issue view N --comments
   ```
2. **判断是否可由 agent 直接实现**
   - Issue 必须带 `ready-for-agent`
   - 如果是 `ready-for-human` / 或需要产品决策 / 或牵涉大范围架构调整但未写清，停止并向人类报告缺的信息。
3. **Ownership / Write scope（强制）**
   - Issue body 必须包含小节：`## Ownership / Write scope`
   - 必须列出“允许修改”的目录/文件（可以额外列出“禁止修改”的共享文件）
   - 若缺失该小节：停止并要求人类补充（否则并行一定踩踏）。
4. **Claim（认领）机制（强制）**
   - 你必须在 Issue 下留 comment 表示你已认领，格式固定：
     - `Claimed-by: <agent_name> @ <YYYY-MM-DD HH:MM>`
   - 如果 Issue 已存在其他人的 `Claimed-by:` 且未明确释放：停止并告知人类。
5. **并发互斥检查（强制）**
   - 每个 Issue 必须用自己的 worktree，路径固定：
     - 分支：`fix/issue-N-<slug>`
     - worktree：`~/Codes/.workspace/fix/issue-N-<slug>/`
   - **若该 worktree 目录已存在**，说明已经有另一个 agent 在做这个 Issue：你必须停止并告知人类重新分配。
6. **确认当前 `~/Codes` 在 `feat`**
   ```bash
   cd ~/Codes
   git status -sb
   # 期望看到：## feat
   ```

### 2. Agent 创建分支 + worktree（并行模式；禁止 checkout -b）

> 并行时绝对不要在 `~/Codes/` 里 `git checkout -b`，那会把共享的 `feat` worktree 切走，导致冲突。

```bash
cd ~/Codes
mkdir -p .workspace

# slug 生成规则（强制一致，避免互斥失效/目录重复）：
# - 全小写；用 - 分隔；只保留字母数字和 -
# - 最长 40 字符（超出截断）
# - 示例：Issue 标题 “GroupTest: Split Modules Skeleton”
#   slug = group-test-split-modules-skeleton

git branch fix/issue-N-<slug> feat
git worktree add .workspace/fix/issue-N-<slug> fix/issue-N-<slug>

cd .workspace/fix/issue-N-<slug>
git status -sb
# 期望看到：## fix/issue-N-<slug>
```

### 3. Agent 实现与提交（增量提交 + 只做本 Issue）

> **修改一步觉得没问题了就先提交**，多个小提交后做完任务，再统一 merge 回 feat。
> 这样每步都可倒退，避免大改出问题难以定位。

1. 修改前后都要看：
   ```bash
   git status && git diff
   ```
2. **增量提交**：每做完一个自包含的小改动就提交一次（可多个 commit）
3. 提交前必须输出摘要：
   ```bash
   git diff --stat
   ```
4. Commit message 必须带 refs：
   ```bash
   git add .
   git commit -m "<type>: <描述> (refs #N)"
   ```

### 4. Agent 完成后如何合并（并行默认：不自动合回 feat）

> 为避免多个 agent 同时 merge 造成冲突放大：  
> **并行模式下，agent 完成后默认只提交到自己的 `fix/issue-N-*` 分支，不要合回 `feat`。**
>
> 合并顺序由人类（或人类明确指定的“集成 agent”）统一执行：`fix/* → feat → master`。

完成 Issue 后，你需要额外做两件事：
1. 确保工作区 clean：`git status`
2. 在 Issue 下留 comment：
   - `Done-by: <agent_name> @ <YYYY-MM-DD HH:MM>`
   - 附上：`git diff --stat` 摘要 + 手工回归步骤 + 可能的冲突点

#### （可选）你被明确指定为“集成 agent”时，才允许你合回 `feat`

#### A) 合回 `feat`（可由 agent 执行）

```bash
# 1) 回到共享的 feat worktree
cd ~/Codes
git checkout feat

# 2) 合并分支到 feat（用 --no-ff 保留分支拓扑）
git merge --no-ff fix/issue-N-<slug>

# 3) 删除分支 + worktree（避免占坑影响并行）
git branch -d fix/issue-N-<slug>
git worktree remove .workspace/fix/issue-N-<slug>
rm -rf .workspace/fix/issue-N-<slug>
```

#### B) 合入 `master` + push（由人类决定）

> 合并顺序由人类统一决定：`fix/* → feat → master`。
> Agent 只合到 `feat`，**合入 master + push 由人类确认后手动执行**。

```bash
cd ~/Codes-master-server
git merge feat --no-ff -m "merge: feat to master (<YYYY-MM-DD>)"
git push origin master
```

## Issue 驱动的开发工作流

```
  GitHub Issues ──→ 逐个实现 ──→ git commit + close issue
  (独立可抓取)       (见下方规则)
```

### 1. 任务来源：GitHub Issues

- 所有任务以 GitHub Issues 为准，`gh issue list` 或 `gh issue view <N>` 查看。

### 2. Issue 创建规范

- 每个 Issue 必须是**独立可实现的垂直切片**（切过所有集成层），不是水平单层。
- Issue body 包含：涉及文件、问题描述、方案概要、预期收益。
- 标签：`enhancement` + `ready-for-agent`（AFK 可实现）或 `ready-for-human`（需人决策）。

### 3. 实现规则

实现一个 Issue 时：

1. **先读 `CONTEXT.md`** — 了解领域术语和已知坑点
2. **检查 `docs/adr/`** — 是否已有相关架构决策
3. **读 `memory` (`/memories/repo/`)** — 之前是否有相关经验记录
4. **按顺序执行 TODO.md 中的 Issue** — #2 → #3 → #4 → #5 → #6，因为 #3-4 依赖 #2（FactorRunResult），#5-6 相对独立
5. **每个 Issue 完成后**：git commit + 关闭 Issue（不要手动改 `TODO.md`，它已被 GitHub Issues 取代）

### 4. Commit 规范

- 格式：`<type>: <简短描述> (refs #issue号码)`
- type: `refactor` / `fix` / `feat` / `docs` / `test`
- 示例：`refactor: extract FactorRunResult from 8 tester dicts (refs #2)`

### 5. 决策记录

- 任何非平凡的架构决策（如"保留而非移除"、"选 A 不选 B"）写 `docs/adr/` 记录。
- ADR 编号递增：`001-xxx.md`, `002-xxx.md`, ...

## 分支策略

- **根目录**：`/Users/maxdeux/Documents/GTHT/Codes/`（此后记为 `~/Codes/`）
- **远程仓库**：`origin` → `https://github.com/maix00/FactorTester.git`
- **`.gitignore`**：已配置忽略 `.workspace/`、`.DS_Store`、`__pycache__/`、`.env` 等常用项
- **`TODO.md`**：已废弃，任务跟踪以 GitHub Issues 为准。如果 repo 中仍存在 `todo.md`，应删除。

```
master ────────────────────────── (线上唯一分支，稳定版本)
  │
  └── feat ───────────────────── (本地持续开发基线，稳定后 merge → master)
         │
         ├── fix/issue-1-xxx     (每个 Issue 独立分支，完成后 merge → feat)
         ├── fix/issue-2-xxx
         └── ...
```

- **`master`**：线上唯一分支，永远稳定。只在 `feat` 稳定后 merge。
- **`feat`**：本地持续开发分支。所有新功能先到 `feat`，稳定后整体 merge 到 `master` 并 push。
- **`fix/issue-N-xxx`**：每个 GitHub Issue 从 `feat` 切出独立分支。完成后 merge 回 `feat`，删除该分支。
- **禁止**：直接在 `master` 上 commit；不要推 `feat` 及其他工作分支到远程（远程只保留 `master`）。

### 更新 AGENTS.md 自身（同步到所有分支和远程）

AGENTS.md 是全仓共用的 Agent 配置文件。更新它时，由人类调度（同一时间只让一个 agent 改），**在 master 上修改并在 master 提交，然后 merge 回 feat**，最后推送到远程：

```bash
# 0. 确认当前在 master worktree
cd ~/Codes-master-server
git checkout master

# 1. 编辑 AGENTS.md 后单独 staged
git add AGENTS.md

# 2. 提交
git diff --cached --stat
git commit -m "docs: <描述>"

# 3. push 到远程 master
git push origin master

# 4. 切到 feat 并 merge master
cd ~/Codes
git checkout feat
git merge master --no-ff -m "merge: master to feat (<描述>)"
```

> 注意：AGENTS.md 的修改在 master 上直接提交，不从 feat merge 到 master。feat 通过 merge master 接收更新。

### Flask 服务器隔离（git worktree）

Agent 在 `fix/issue-*` 分支上改代码时，Flask 从独立的 `master` 目录运行，互不干扰：

```bash
# 一次性：创建 master 独立 worktree
git worktree add ../Codes-master-server master
```

两个 VS Code 窗口：
1. **窗口 A**：打开 `~/Codes/` — agent 工作区，`feat`/`fix/issue-*` 分支，断点会漂移
2. **窗口 B**：打开 `~/Codes-master-server/` — 始终 `master`，F5 启动 `Flask: start_server`，设断点调试

> 窗口 B 需单独复制或创建 `.vscode/launch.json`（内容同窗口 A 的 `Flask: start_server`）。

| 目录 | 分支 | 用途 |
|------|------|------|
| `~/Codes/` | `feat` / `fix/issue-*` | agent 工作区 |
| `~/Codes-master-server/` | `master`（worktree） | Flask 服务器 |

### 多 Agent 并行工作区（`.workspace/`）

当多个 agent 同时操作不同 Issue 时，每个 agent 在 `.workspace/` 下拥有独立 worktree，互不干扰。

---

## 🚫🛑 MERGE 权限（最高优先级 — 覆盖所有其他规则）

> # ⛔ 以下规则凌驾于所有其他规则之上。违反即严重事故。

| 操作 | Agent 权限 | 规则 |
|------|-----------|------|
| `fix/* → feat` merge | ❌ **禁止** | 必须人类明确说"合并"、"merge"或同意后才能执行 |
| `feat → master` merge | ❌ **禁止** | 必须人类明确说"合并"、"merge"或同意后才能执行 |
| `git push origin master` | ❌ **禁止** | 必须人类明确说"push"或同意后才能执行 |
| `git push`（任何远程） | ❌ **禁止** | 同上，包括 push 任何分支到远程 |
| worktree 内的 commit | ✅ 允许 | 在自己的 `fix/issue-N-*` worktree 内自由提交 |

**Agent 在任何情况下都不得自行判断合并时机。** 即使认为任务已完成、测试已通过、代码已就绪，也必须：
1. 在 Issue 下留 `Done-by:` comment，附上 `git diff --stat` 摘要
2. **等待人类明确指示** "合并到 feat" 或 "merge to feat/master"

> 人类说的 "好的"、"可以"、"合并吧"、"merge"、"push" 等即为同意。
> 人类说的 "你自己看着办"、"你决定" **不等于** 同意 merge —— merge 必须**显式**同意。

---

#### ⚠️ 并发控制（强制）

> 🛑🛑🛑 **以下规则必须严格遵守，违规可能导致并发冲突、数据丢失。** 🛑🛑🛑

**权限分层（Agent 启动时自我判定）**：
- **VS Code Agent（低权限）**：可以正常执行命令和提交代码。**所有 merge 和 push 必须经人类同意（见上方 🚫🛑 MERGE 权限）。**
- **Codex Agent（高权限）**：可以执行任务所需的常规写操作（创建/修改文件、commit 等）。写操作前输出提示语句说明意图；高风险或破坏性操作（如 `rm -rf`、`git reset --hard`、force push、删除远程分支、直接推送远程）以及**所有 merge 和 push** 仍需人类明确确认。

**人类调度（唯一并发控制）**：
- 人类负责分配 Issue 给 agent，不给同一个 Issue 分配给多个 agent。
- 每个 Issue 的 fix 分支 + worktree 用 Issue 编号唯一标识：`fix/issue-<N>-<描述>` / `.workspace/fix/issue-<N>-<描述>/`。
- Agent 检查 `.workspace/fix/issue-<N>-<描述>/` 是否已存在 → 存在则说明已有 agent 在处理该 Issue，Agent 应停止并提示人类。
- 不需要额外锁：Issue 编号天然隔离，worktree 目录存在即互斥。

#### 目录结构

```
Codes/
  .workspace/                  ← git ignored，每个 agent 一个子目录
    fix/issue-2-factor-result/ ← agent A 的 fix 分支 worktree
    fix/issue-3-ic-test/       ← agent B 的 fix 分支 worktree
    ...
```
> 注：`~/Codes/` 本身在 `feat` 分支，作为所有 agent 的共享基线。不需在 `.workspace/` 下重复创建 `feat` worktree。

#### Agent 首次启动流程

> **前提**：你的 VS Code 窗口已经打开 `~/Codes/` 并位于 `feat` 分支。
> `feat` 已被当前窗口作为 worktree 使用，**不会再在 `.workspace/` 下重复创建 `feat` 的 worktree**。

0. **必须在 GitHub 上创建 Issue**（`gh issue create`），标记 `ready-for-agent`。不创建 Issue 不得开始修改代码。
1. **确保 `.workspace/` 已加入 `.gitignore`**（仓库已配置，无需再改）
2. **在当前 `~/Codes/`（feat 分支）上创建 fix 分支，并在 `.workspace/` 下为其创建独立 worktree**：
   ```bash
   cd ~/Codes
   mkdir -p .workspace
   git branch fix/issue-<N>-<描述> feat               # ✅ 创建分支但不切换（feat 仍是当前分支）
   git worktree add .workspace/fix/issue-<N>-<描述> fix/issue-<N>-<描述>  # 在 .workspace 下建 worktree
   ```
   > ⚠️ **不能用 `git checkout -b`** — 那会把当前目录切到新分支，导致 `git worktree add` 报 `already used by worktree`。
   > 正确做法：`git branch <新分支> feat` + `git worktree add .workspace/... <新分支>`。
3. **在 `.workspace/` 下的独立 worktree 中工作**：
   ```bash
   cd .workspace/fix/issue-<N>-<描述>
   # 修改代码、运行测试、提交
   ```
   > 此时你有两个目录：`~/Codes/` 在 `feat` 分支，`.workspace/fix/issue-<N>-<描述>/` 在 fix 分支。互不干扰。

#### Agent 完成任务后（⚠️ 不可自行 merge — 见上方 🚫🛑 MERGE 权限）

```bash
# 1. 在 worktree 内 commit
cd .workspace/fix/issue-<N>-<描述>
git add .
git commit -m "<type>: <描述> (refs #<N>)"

# 2. 在 Issue 下留 Done-by comment，等待人类指示 merge
```

> ⛔ Agent **不得**自行执行以下操作。必须等待人类明确同意：
> ```bash
> # 以下操作需要人类同意后执行：
> cd ~/Codes
> git checkout feat
> git merge --no-ff fix/issue-<N>-<描述>   # --no-ff 保留分支拓扑
> git branch -d fix/issue-<N>-<描述>
>
> # 删除 worktree（在主目录执行）
> git worktree remove .workspace/fix/issue-<N>-<描述>
> rm -rf .workspace/fix/issue-<N>-<描述>
> ```

#### 关键规则

- ✅ 每个 agent 在自己的 `.workspace/fix/issue-*` 下操作，互不干扰
- ✅ 所有 worktree 共享同一个 `.git`，merge 无障碍
- ✅ `.workspace/` 已被 gitignore，不会污染仓库
- ❌ 不要在 `.workspace/` 下直接 `git push`（远程只保留 `master`）
- ❌ 不要跨 agent 的 worktree 互相修改文件

### Git + GitHub CLI 自动化工作流

> 只依赖 `git` + `gh`，不需要 GitKraken。

> ✅ 本仓统一使用 **worktree 分支流程**（单人/并行都一样）。这样可以一劳永逸地避免：
> - 把共享的 `~/Codes`（feat worktree）切走导致 worktree 冲突
> - 并行时不同 agent 互相污染工作区状态
>
> 因此：**本仓不再提供 `git checkout -b ...` 的流程**（即使单人也不要用）。

### 0. 前提检查

开始前检查环境：

```bash
git --version
gh --version
gh auth status
git remote -v
git status
```

如果 `gh auth status` 未登录，提示先运行 `gh auth login`。

> 当前机器的交互式 Terminal（例如 `base` 环境）通过 macOS keyring 使用 `gh` 凭据。
> Codex/自动化 shell 可能无法读取 keyring，因而把同一账号误报为 `token invalid`。
> 如果用户终端中的 `gh auth status` 显示已登录、而 agent shell 显示失败，优先按“keyring 隔离”处理，不要据此判断用户未登录。

### 1. 读取 Issue

```bash
gh issue view <号码> --comments
```

### 2. 创建工作分支（统一 worktree 流程）

```bash
cd ~/Codes
git checkout feat
git pull origin master  # 确保 feat 基于最新 master（仅更新远端 master 的基线）

mkdir -p .workspace
git branch fix/issue-<号码>-<简短描述> feat
git worktree add .workspace/fix/issue-<号码>-<简短描述> fix/issue-<号码>-<简短描述>

cd .workspace/fix/issue-<号码>-<简短描述>
```

### 3. 修改代码

修改前看状态：`git status && git diff`

修改后必须运行项目检查（根据项目类型自动判断，如 `pytest`）。

### 4. 提交 Commit

提交前展示 `git diff --stat` 摘要：

```bash
git add .
git commit -m "<type>: <描述> (refs #<号码>)"
```

### 5. 合并回 feat（⛔ 必须人类同意）

> 参考上方 🚫🛑 MERGE 权限。Agent 不得自行执行。

```bash
cd ~/Codes
git checkout feat
git merge --no-ff fix/issue-<号码>-<简短描述>   # --no-ff 保留分支拓扑
git branch -d fix/issue-<号码>-<简短描述>

# 删除 worktree（避免占坑）
git worktree remove .workspace/fix/issue-<号码>-<简短描述>
rm -rf .workspace/fix/issue-<号码>-<简短描述>
```

全部 Issue 完成后，`feat → master`（⛔ 必须人类同意）：

```bash
git checkout master && git merge feat --no-ff
git push origin master
```

### 安全规则

- ❌ 不 force push
- ❌ 不擅自删除远程分支
- ❌ 不擅自关闭 Issue
- ❌ 不提交 secrets / token / 密码 / `.env`
- ❌ **不自行 merge（fix→feat, feat→master）— 见 🚫🛑 MERGE 权限**
- ❌ **不自行 push 任何分支到远程（包括 master 和其他）— 见 🚫🛑 MERGE 权限**
- ✅ 大改动前先解释计划
- ✅ 每次 commit 前展示 `git diff` 摘要
- ✅ 测试失败先修复，修不了说明原因
- ✅ merge/push 前必须获得人类明确同意
