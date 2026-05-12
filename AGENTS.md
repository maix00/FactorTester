# FactorTester — Agent Configuration

## Agent skills

- **Issue tracker**: GitHub Issues — `gh` CLI against `maix00/FactorTester`. See `docs/agents/issue-tracker.md`.
- **Triage labels**: Default — `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.
- **Domain docs**: Single-context — one `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.

## Issue 驱动的开发工作流

```
  TODO.md ──→ GitHub Issues ──→ 逐个实现 ──→ git commit + close issue
  (索引)       (独立可抓取)       (见下方规则)
```

### 1. 任务来源：`TODO.md`

- `TODO.md` 是**轻量索引**，每条指向对应的 GitHub Issue。
- 当新任务产生时，先写 TODO.md 条目，再同步到 GitHub Issue。
- 完成一条后，在 TODO.md 将 `⬜` 改为 `✅`，附上 commit/PR 引用。

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
5. **每个 Issue 完成后**：更新 TODO.md 状态 + git commit + 关闭 Issue

### 4. Commit 规范

- 格式：`<type>: <简短描述> (refs #issue号码)`
- type: `refactor` / `fix` / `feat` / `docs` / `test`
- 示例：`refactor: extract FactorRunResult from 8 tester dicts (refs #2)`

### 5. 决策记录

- 任何非平凡的架构决策（如"保留而非移除"、"选 A 不选 B"）写 `docs/adr/` 记录。
- ADR 编号递增：`001-xxx.md`, `002-xxx.md`, ...

## 分支策略

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

1. **确保 `.workspace/` 已加入 `.gitignore`**（仓库已配置，无需再改）
2. **在当前 `~/Codes/`（feat 分支）上创建 fix 分支，并在 `.workspace/` 下为其创建独立 worktree**：
   ```bash
   cd ~/Codes
   mkdir -p .workspace
   git checkout -b fix/issue-<N>-<描述>          # 从 feat 创建 fix 分支
   git worktree add .workspace/fix/issue-<N>-<描述> fix/issue-<N>-<描述>  # 为 fix 分支建 worktree
   ```
   ⚠️ **然后立刻切回 `feat`**，让原窗口继续使用 `feat`：
   ```bash
   git checkout feat
   ```
3. **在 `.workspace/` 下的独立 worktree 中工作**：
   ```bash
   cd .workspace/fix/issue-<N>-<描述>
   # 修改代码、运行测试、提交
   ```
   > 此时你有两个目录：`~/Codes/` 在 `feat` 分支，`.workspace/fix/issue-<N>-<描述>/` 在 fix 分支。互不干扰。

#### Agent 完成任务后

```bash
# 1. 在 worktree 内 commit
cd .workspace/fix/issue-<N>-<描述>
git add .
git commit -m "<type>: <描述> (refs #<N>)"

# 2. 回到主目录的 feat，合并 fix 分支
cd ~/Codes
git checkout feat
git merge fix/issue-<N>-<描述>
git branch -d fix/issue-<N>-<描述>

# 3. 删除 worktree（在主目录执行）
git worktree remove .workspace/fix/issue-<N>-<描述>
rm -rf .workspace/fix/issue-<N>-<描述>
```

#### 关键规则

- ✅ 每个 agent 在自己的 `.workspace/fix/issue-*` 下操作，互不干扰
- ✅ 所有 worktree 共享同一个 `.git`，merge 无障碍
- ✅ `.workspace/` 已被 gitignore，不会污染仓库
- ❌ 不要在 `.workspace/` 下直接 `git push`（远程只保留 `master`）
- ❌ 不要跨 agent 的 worktree 互相修改文件

### Git + GitHub CLI 自动化工作流

> 只依赖 `git` + `gh`，不需要 GitKraken。

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

### 1. 读取 Issue

```bash
gh issue view <号码> --comments
```

### 2. 创建工作分支

```bash
git checkout feat && git pull origin master  # 确保 feat 基于最新 master
git checkout -b fix/issue-<号码>-<简短描述>
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

### 5. 合并回 feat

```bash
git checkout feat && git merge fix/issue-<号码>-<简短描述>
git branch -d fix/issue-<号码>-<简短描述>
```

全部 Issue 完成后，`feat → master`：

```bash
git checkout master && git merge feat --no-ff
git push origin master
```

### 安全规则

- ❌ 不 force push
- ❌ 不擅自删除远程分支
- ❌ 不擅自关闭 Issue
- ❌ 不提交 secrets / token / 密码 / `.env`
- ✅ 大改动前先解释计划
- ✅ 每次 commit 前展示 `git diff` 摘要
- ✅ 测试失败先修复，修不了说明原因
