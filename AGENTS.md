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

## Git + GitHub CLI 自动化工作流

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

总结：Issue 要求 → 涉及文件 → 修改方案 → 是否需要测试 → 有无不明确之处。

### 2. 创建工作分支

```bash
git checkout main && git pull
git checkout -b fix/issue-<号码>-<简短描述>
```

### 3. 修改代码

修改前看状态：`git status && git diff`

修改后必须运行项目检查（根据 `package.json` / `pyproject.toml` / `Makefile` 自动判断）。

### 4. 提交 Commit

提交前展示 `git diff --stat` 摘要：

```bash
git add .
git commit -m "<type>: <描述> (refs #<号码>)"
```

### 5. 推送 + 创建 PR

```bash
git push -u origin fix/issue-<号码>-<简短描述>
gh pr create \
  --title "<type>: <描述> (closes #<号码>)" \
  --body "Closes #<号码>

## Summary
- ...

## Tests
- ..."
```

PR body 中 `Closes #<号码>` 会在 PR 合并后自动关闭 Issue。

### 6. 直接关闭 Issue（仅明确要求时）

```bash
gh issue close <号码> --comment "Fixed in commit <hash>." --reason completed
```

### 安全规则

- ❌ 不 force push
- ❌ 不擅自删除分支
- ❌ 不擅自关闭 Issue（PR 中 `Closes #` 自动关闭除外）
- ❌ 不提交 secrets / token / 密码 / `.env`
- ✅ 大改动前先解释计划
- ✅ 每次 commit 前展示 `git diff` 摘要
- ✅ 测试失败先修复，修不了说明原因
