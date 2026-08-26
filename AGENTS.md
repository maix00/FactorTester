# FactorTester — Agent Configuration

## Agent skills

- **Issue tracker**: GitHub Issues — `gh` CLI against `maix00/FactorTester`. See `docs/agents/issue-tracker.md`.
- **Triage labels**: Default — `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.
- **Domain docs**: Single-context — one `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.

## “被分配 Issue 号即可开工”的总流程（并行友好 / 多 Agent）

> 目标：人类只需要对 agent 说一句“你负责 Issue #N”，agent 就能自行判断能否开工、如何隔离并行、做完如何回到共享的 `origin/feat`，以及什么时候由人类合入 `main`。

### 0. 现成解决方案（为什么这样设计）

并行协作里最稳定的一套组合是：

1. **一任务一分支 + 一任务一工作区**：用 `git worktree` 为每个任务创建独立目录，减少互相污染（每个 worktree 有自己的 `HEAD`/`index` 等元数据）。citeturn1search1turn1search4  
2. **显式 Claim（认领）机制**：用 Issue comment / assignee 表示“谁在做”，避免重复劳动；GitHub 本身也支持把 Issue assign 给某个用户。citeturn1search2turn1search7  
3. **Ownership（写入范围）**：每个 Issue 明确允许修改的目录/文件；更强约束可用 `CODEOWNERS` 来表达代码归属/审阅责任。citeturn1search0turn1search5  
4. **远端集成基线 + 顺序 merge**：`origin/feat` 是所有设备共同的开发基线；并行开发，逐个同步、合入和发布，降低冲突放大。

本仓默认采用：**worktree 隔离 + Issue claim + Ownership + `origin/feat` 共享基线 + 人类顺序 merge**。

### 0.1 当前日常改动边界（最新人类指令）

多台设备和多个 Agent 共同开发时，`origin/feat` 是唯一开发集成基线；不得创建
长期 `feat-2`、`feat-device-*` 等平行集成分支。以下规则优先于旧的“在本地
`feat` 直接修改”流程：

- **所有改动都使用短期任务分支和独立 worktree**。小改动可使用
  `codex/<short-slug>`；已有 Issue 或大改动使用 `fix/issue-N-<slug>`。本地
  `feat` 只作为 `origin/feat` 的干净镜像和获授权后的集成入口，不承载开发修改。
- **小改动不强制新建 Issue**：包括局部 UI/文案调整、单个组件行为修复、已有
  功能的兼容性修补、测试与文档更新，以及不改变接口、数据库或部署拓扑的
  小范围重构；但仍必须使用短期分支。
- **大改动必须创建 Issue、独立分支和 worktree**：包括数据库 schema 或迁移、
  认证/权限模型、服务器网络拓扑、Docker/Compose/WireGuard、发布流程、
  跨模块架构、公共协议/API 变更、长文件语义拆分，以及可能与其他 agent
  并行冲突的改动。
- 无法明确判断规模时按大改动处理；如果改动虽小但正在被另一个 worktree
  修改同一文件，也按大改动隔离。
- **任务分支默认只保留在本地 worktree，不得自行推送同名远端分支**。只有人类
  明确要求共享某个任务分支时，才可推送该分支；常规远端只保留 `feat` 与
  `main`。
- 人类明确授权 `codex/*` 或 `fix/* → feat` 合并时，该授权包含集成前后的
  `origin/feat` 同步、必要的冲突处理和聚焦复测，以及把结果 `git push origin
  feat`。`feat → main`、`origin/main` push 和生产部署仍须另行明确授权。
- 当前线上稳定分支为 `main`；本文件中历史流程使用的 `master` 均按 `main`
  理解。
- 不得为了清理而强删含有未提交或被忽略文件的 worktree；先保留并报告，待
  人类确认后再处理。

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
   - Issue 评论中的最新生命周期状态是互斥依据：存在未被 `Done-by:` 或明确释放终止的 `Claimed-by:`，说明已有 agent 正在处理，必须停止并告知人类。
   - **若该 worktree 目录已存在**，先检查 Issue 状态，不得直接删除或重复创建：
     - 仍处于 Claim 状态：停止并告知人类。
     - 已有 `Done-by:` 且人类明确要求继续该 Issue：复用原 branch/worktree。
     - 已有 `Done-by:` 但当前任务不是继续该 Issue：不要进入或修改该 worktree。
6. **确认当前 `~/Codes` 在 `feat`**
   ```bash
   cd ~/Codes
   git status -sb
   # 期望看到：## feat...origin/feat，且工作区 clean
   ```
7. **同步共享开发基线**
   ```bash
   git fetch origin --prune
   git status -sb
   git merge --ff-only origin/feat
   git rev-list --left-right --count origin/feat...feat
   # 必须输出：0  0
   ```
   - 若工作区不干净：不得 pull、merge 或 stash 他人的改动；改用独立 worktree，
     或先由原任务负责人处理。
   - 若 `--ff-only` 失败，或 `rev-list` 不是 `0 0`：说明本地 `feat` 含未发布
     提交或已与远端分叉；停止新任务，先按“共享 feat 同步与发布”流程完成整合，
     禁止 reset 或 force push。

### 2. Agent 创建短期分支 + worktree（禁止 checkout -b）

> 并行时绝对不要在 `~/Codes/` 里 `git checkout -b`，那会把共享的 `feat` worktree 切走，导致冲突。

```bash
cd ~/Codes
git fetch origin --prune
git merge --ff-only origin/feat
mkdir -p .workspace

# slug 生成规则（强制一致，避免互斥失效/目录重复）：
# - 全小写；用 - 分隔；只保留字母数字和 -
# - 最长 40 字符（超出截断）
# - 示例：Issue 标题 “GroupTest: Split Modules Skeleton”
#   slug = group-test-split-modules-skeleton

git branch fix/issue-N-<slug> origin/feat
git worktree add .workspace/fix/issue-N-<slug> fix/issue-N-<slug>

cd .workspace/fix/issue-N-<slug>
git status -sb
# 期望看到：## fix/issue-N-<slug>
```

没有 Issue 的小改动使用同样流程，但分支和目录改为
`codex/<short-slug>` / `.workspace/codex/<short-slug>/`。不得在本地 `feat`
直接编辑，也不得用长期设备分支代替任务分支。

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
   无 Issue 的小修复使用 `git commit -m "<type>: <描述>"`，不得伪造 Issue 编号。
5. 提交并通过聚焦测试后同步共享基线：
   ```bash
   git fetch origin
   git merge origin/feat
   # 若吸收了新提交或解决了冲突，重新运行聚焦测试
   ```
   吸收共享基线后重新运行聚焦测试。不得自行推送任务分支；仅在人类明确要求
   共享该分支时才执行 `git push -u origin <task-branch>`，且禁止 force push。

### 4. Agent 完成后如何合并（并行默认：不自动合回 feat）

> 为避免多个 agent 同时 merge 造成冲突放大：  
> **并行模式下，agent 完成后默认只提交本地 `codex/*` 或 `fix/issue-N-*`
> 任务分支，不推送任务分支，也不自行合回 `feat`。**
>
> 合并顺序由人类（或人类明确指定的“集成 agent”）统一执行：`fix/* → origin/feat → main`。

完成任务后，你需要额外做两件事：
1. 确保工作区 clean：`git status`
2. 有 Issue 时在 Issue 下留 comment；无 Issue 的小修复向人类直接报告：
   - `Done-by: <agent_name> @ <YYYY-MM-DD HH:MM>`
   - 附上：`git diff --stat` 摘要 + 手工回归步骤 + 可能的冲突点

#### （可选）你被明确指定为“集成 agent”时，才允许你合回 `feat`

#### A) 合回 `feat`（可由 agent 执行）

```bash
# 1) 回到共享的 feat worktree，并确认没有其他任务的未提交修改
cd ~/Codes
git checkout feat
git status -sb

# 2) 先同步远端 feat；本地 feat 必须能快进到共享基线
git fetch origin --prune
git merge --ff-only origin/feat

# 3) 合并分支到 feat（用 --no-ff 保留分支拓扑）
git merge --no-ff fix/issue-N-<slug>

# 4) 运行聚焦测试后，再次吸收合并期间出现的远端提交
git fetch origin
git merge origin/feat
# 若产生新 merge 或冲突，解决后必须重新运行聚焦测试

# 5) 发布共享 feat；若被 non-fast-forward 拒绝，返回第 4 步，禁止 force push
git push origin feat

# 6) 默认保留 fix 分支和 worktree，便于回归、补丁和同一 Issue 继续迭代
git status -sb
```

> **合并与清理是两个独立动作。** 合并后默认保留 branch/worktree；只有人类明确说“清理/删除 worktree（及分支）”时，agent 才能执行清理。保留的已完成 worktree 不表示仍被认领，认领状态以 Issue 中最新的 `Claimed-by:` / `Done-by:` 为准。

#### B) 合入 `main` + push（由人类决定）

> 合并顺序由人类统一决定：`fix/* → origin/feat → main`。
> Agent 只合到并发布 `origin/feat`，**合入 main + push 由人类另行确认**。

```bash
cd ~/Codes-main-server
git fetch origin --prune
git merge --ff-only origin/main
git merge origin/feat --no-ff -m "merge: feat to main (<YYYY-MM-DD>)"
git push origin main
```

## Issue 驱动的大改动工作流

```
  GitHub Issues ──→ 逐个实现 ──→ git commit + close issue
  (独立可抓取)       (见下方规则)
```

### 1. 任务来源

- 大改动和已分配 Issue 的任务以 GitHub Issues 为准，使用 `gh issue list` 或
  `gh issue view <N>` 查看。
- 人类直接要求的小修复可以不创建 Issue，但必须使用一次性的 `codex/<slug>`
  分支和独立 worktree，并遵守同样的同步、测试与集成规则。

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
origin/main ───────────────────────────── (线上稳定分支)
     │
     └── origin/feat ──────────────────── (唯一共享开发集成分支)

local codex/* / fix/issue-N-* ─────────── (仅本地短期任务分支 + worktree)
```

- **`origin/main`**：线上唯一稳定分支，只接收获授权的 `origin/feat` 发布。
- **`origin/feat`**：所有设备共享的唯一开发集成分支；本地 `feat` 必须保持为其
  干净镜像，禁止直接开发和 force push。
- **任务分支**：一项任务一个本地短期分支，从最新 `origin/feat` 创建；默认不
  推送，获授权后串行合入 `origin/feat`。只有人类明确要求共享某个任务分支时
  才推送该分支，并在用途结束后清理。
- **禁止**：建立长期 `feat-2` 或设备专属集成分支、直接在 `main` 开发、把
  `origin/feat` reset 到某台设备的本地状态，或 force push 共享分支。
- GitHub 上应保护 `main` 和 `feat`：禁止 force push 与删除；`feat` 仅允许
  获授权的集成操作写入。分支保护是最后防线，不能替代 fetch、复测和
  non-fast-forward 重试流程。

### 更新 AGENTS.md 自身（同步到所有分支和远程）

AGENTS.md 是全仓共用的 Agent 配置文件。更新它时，由人类调度（同一时间只让
一个 agent 改），**在 main 上修改、提交并推送，再把 `origin/main` 合入
`origin/feat`**：

```bash
# 0. 确认当前在 main worktree，并同步远端 main
cd ~/Codes/.workspace/integration/main
git checkout main
git fetch origin --prune
git merge --ff-only origin/main

# 1. 编辑 AGENTS.md 后单独 staged
git add AGENTS.md

# 2. 提交
git diff --cached --stat
git commit -m "docs: <描述>"

# 3. push 到远程 main
git push origin main

# 4. 在干净的 feat worktree 同步并合入 origin/main
cd ~/Codes
git checkout feat
git fetch origin --prune
git merge --ff-only origin/feat
git merge origin/main --no-ff -m "merge: main to feat (<描述>)"
git fetch origin
git merge origin/feat
git push origin feat
```

> 注意：AGENTS.md 的修改在 main 上直接提交，不从 feat merge 到 main；
> `origin/feat` 通过合入 `origin/main` 接收更新。任何 non-fast-forward 拒绝都必须
> 重新 fetch、合并和复测，禁止 force push。

### Flask 服务器隔离（git worktree）

Agent 在任务分支上改代码时，稳定服务从独立的 `main` 目录运行，互不干扰：

```bash
# 一次性：创建 main 独立 worktree
git worktree add .workspace/integration/main main
```

两个 VS Code 窗口：
1. **窗口 A**：打开任务 worktree — `codex/*` 或 `fix/issue-*` 开发区
2. **窗口 B**：打开 `~/Codes/.workspace/integration/main/` — 始终 `main`，用于稳定版本与发布检查

> 窗口 B 需单独复制或创建 `.vscode/launch.json`（内容同窗口 A 的 `Flask: start_server`）。

| 目录 | 分支 | 用途 |
|------|------|------|
| `~/Codes/` | `feat` | `origin/feat` 的干净镜像与集成入口 |
| `~/Codes/.workspace/codex/*` / `.workspace/fix/*` | 任务分支 | agent 工作区 |
| `~/Codes/.workspace/integration/main/` | `main`（worktree） | 稳定版本与发布检查 |

### 多 Agent 并行工作区（`.workspace/`）

当多个 agent 同时操作不同 Issue 时，每个 agent 在 `.workspace/` 下拥有独立 worktree，互不干扰。

---

## 🚫🛑 MERGE 权限（最高优先级 — 覆盖所有其他规则）

> # ⛔ 以下规则凌驾于所有其他规则之上。违反即严重事故。

| 操作 | Agent 权限 | 规则 |
|------|-----------|------|
| 任务分支 commit | ✅ 允许 | 仅限自己的本地 `codex/*` 或 `fix/issue-N-*`；先同步 `origin/feat` |
| 任务分支 push | ❌ **默认禁止** | 只有人类明确要求共享该任务分支时才允许；禁止 force push |
| `codex/*` / `fix/* → feat` merge + `push origin feat` | ❌ **默认禁止** | 必须人类明确说“合并”或同意；授权后，同步与 push 是该集成动作的必要组成 |
| `feat → main` merge | ❌ **禁止** | 必须人类明确说“合并”或同意后才能执行 |
| `git push origin main` | ❌ **禁止** | 必须人类明确说“push”或同意后才能执行 |
| 其他远程或共享分支 push | ❌ **禁止** | 不得自行创建长期集成分支或推送无关分支 |

**Agent 在任何情况下都不得自行判断合并时机。** 即使认为任务已完成、测试已通过、代码已就绪，也必须：
1. 有 Issue 时在 Issue 下留 `Done-by:` comment，附上 `git diff --stat` 摘要；
   无 Issue 的小修复直接向人类报告同样的信息
2. **等待人类明确指示** “合并到 feat”或“merge to feat/main”

> 人类说的 "好的"、"可以"、"合并吧"、"merge"、"push" 等即为同意。
> 人类说的 "你自己看着办"、"你决定" **不等于** 同意 merge —— merge 必须**显式**同意。

---

#### ⚠️ 并发控制（强制）

> 🛑🛑🛑 **以下规则必须严格遵守，违规可能导致并发冲突、数据丢失。** 🛑🛑🛑

**权限分层（Agent 启动时自我判定）**：
- **VS Code Agent（低权限）**：可以在自己的本地短期任务分支执行命令和提交；
  不得自行推送任务分支。合入/推送共享 `feat` 以及合入/推送 `main` 必须经人类同意。
- **Codex Agent（高权限）**：权限边界相同；高风险或破坏性操作（如 `rm -rf`、
  `git reset --hard`、force push、删除远程分支）仍需人类明确确认。

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
> 注：`~/Codes/` 本身在 `feat` 分支，只作为 `origin/feat` 的本地镜像和集成
> 入口。不需在 `.workspace/` 下重复创建 `feat` worktree，也不得直接在其中开发。

#### Agent 首次启动流程

> **前提**：你的 VS Code 窗口已经打开 `~/Codes/` 并位于 `feat` 分支。
> `feat` 已被当前窗口作为 worktree 使用，**不会再在 `.workspace/` 下重复创建 `feat` 的 worktree**。

0. **判断是否需要 Issue**：小修复可直接使用 `codex/<slug>`；大改动必须先在
   GitHub 创建 Issue、标记 `ready-for-agent`，再使用 `fix/issue-N-<slug>`。
1. **确保 `.workspace/` 已加入 `.gitignore`**（仓库已配置，无需再改）
2. **同步本地 feat 镜像，再从 `origin/feat` 创建任务分支和独立 worktree**：
   ```bash
   cd ~/Codes
   git status -sb
   git fetch origin --prune
   git merge --ff-only origin/feat
   mkdir -p .workspace
   git branch fix/issue-<N>-<描述> origin/feat        # ✅ 从共享远端基线创建但不切换
   git worktree add .workspace/fix/issue-<N>-<描述> fix/issue-<N>-<描述>  # 在 .workspace 下建 worktree
   ```
   > ⚠️ **不能用 `git checkout -b`** — 那会把当前目录切到新分支，导致 `git worktree add` 报 `already used by worktree`。
   > 正确做法：`git branch <新分支> origin/feat` + `git worktree add .workspace/... <新分支>`。
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
git fetch origin
git merge origin/feat
# 吸收更新后重新测试

# 2. 在 Issue 下留 Done-by comment，等待人类指示 merge
```

> ⛔ Agent **不得**自行执行以下操作。merge 与清理分别需要人类明确同意：
> ```bash
> # 人类明确同意 merge 后可执行：
> cd ~/Codes
> git checkout feat
> git fetch origin --prune
> git merge --ff-only origin/feat
> git merge --no-ff fix/issue-<N>-<描述>   # --no-ff 保留分支拓扑
> # 测试后再次 fetch/merge origin/feat，再 push；拒绝时重复，禁止 force push
> git fetch origin
> git merge origin/feat
> git push origin feat
>
> # 以下清理操作默认不执行；仅在人类另行明确要求清理时执行：
> git worktree remove .workspace/fix/issue-<N>-<描述>
> git branch -d fix/issue-<N>-<描述>
> ```

#### 关键规则

- ✅ 每个 agent 在自己的 `.workspace/fix/issue-*` 下操作，互不干扰
- ✅ 所有 worktree 共享同一个 `.git`，merge 无障碍
- ✅ `.workspace/` 已被 gitignore，不会污染仓库
- ✅ 从任务 worktree 推送同名短期远端分支，供跨设备集成和接续
- ❌ 不得从任务 worktree 直接 push `origin/feat` 或 `origin/main`
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
git status -sb
git fetch origin --prune
git merge --ff-only origin/feat

mkdir -p .workspace
git branch fix/issue-<号码>-<简短描述> origin/feat
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
git fetch origin
git merge origin/feat
# 吸收更新后重新运行聚焦测试
```

### 5. 合并回 feat（⛔ 必须人类同意）

> 参考上方 🚫🛑 MERGE 权限。Agent 不得自行执行。

```bash
cd ~/Codes
git checkout feat
git status -sb
git fetch origin --prune
git merge --ff-only origin/feat
git merge --no-ff fix/issue-<号码>-<简短描述>   # --no-ff 保留分支拓扑
git fetch origin
git merge origin/feat
# 若吸收了其他设备的提交，重新运行聚焦测试
git push origin feat

# 默认保留 fix 分支和 worktree；清理需要人类另行明确授权
git status -sb
```

发布稳定版本时，`origin/feat → main`（⛔ 必须人类另行同意）：

```bash
cd ~/Codes/.workspace/integration/main
git checkout main
git fetch origin --prune
git merge --ff-only origin/main
git merge origin/feat --no-ff
git push origin main
```

### 安全规则

- ❌ 不 force push
- ❌ 不擅自删除远程分支
- ❌ 不擅自关闭 Issue
- ❌ 不提交 secrets / token / 密码 / `.env`
- ❌ **不自行 merge 到共享 `feat` 或 `main` — 见 🚫🛑 MERGE 权限**
- ❌ **不自行 push 任务分支、`origin/feat` 或 `origin/main`；任一 push 都需符合
  对应的人类明确授权**
- ✅ 大改动前先解释计划
- ✅ 每次 commit 前展示 `git diff` 摘要
- ✅ 测试失败先修复，修不了说明原因
- ✅ merge/push 前必须获得人类明确同意
