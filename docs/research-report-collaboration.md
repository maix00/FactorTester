# 多 Profile 协作同一报告

报告的 `report_id` 不随服务器、客户端或分支变化。分支归属使用完整用户身份与 Profile；同名 `self` 不代表同一个作者。页面分支候选显示「分支 · 管理用户 · Profile」，只有一个候选时也保留显示。

## 查询、撰写和发布

先查看 `factortester research reports --help` 及对应子命令帮助。`branch-status <report-id>` 列出可访问的分支及作者、版本和发布位置。写入要求该 Profile 对研究具有编辑资格；报告仅分享为只读不授予编辑权限。

报告拥有者先用 `factortester research member-add <research-id> --principal <完整用户身份> --profile <profile> --role editor` 授权每个参与的 Profile。同一个用户的另一 Profile 也需要单独登记；服务器端与客户端遵循相同规则。

`branch-fork <report-id> --profile <profile> --from-branch <source> --branch-id <new>` 从已发布的服务器或客户端分支取得完整可编辑快照，在当前 Profile 登记新分支并发布。新分支标识应唯一；重试必须使用原标识，以继续同一次 fork，不能换标识掩盖失败。

本地通过已有 `show`、`add`、`add-batch` 等报告命令编辑；替换内容使用 `add-batch` 的 `op=replace`。之后用 `branch-upload --profile <profile> --work-package-id <package> --branch-id <branch>` 上传完整版本。它检查共享分支版本；发生并发冲突时保留本地工作并报错，不静默覆盖另一作者。

`branch-diff <report-id> --base <branch> --compare <other> --include-content` 比较两个可访问的已发布分支，包含正文、附件及 Job 资源变化。

## 跨 branch 选择性整合

报告拥有者决定最终分支内容。若来源只在另一运行端，先 fork 到自己的一个审阅分支；这同时经过 Manager 权限校验并取得完整文件。不要直接读取其他用户的本地 Profile 目录。

在同一报告的两个本地已登记分支间：

```bash
factortester research reports copy-preview \
  --profile self --work-package-id <package> --branch-id main \
  --source-branch-id <review-branch> --component-id <chapter-or-section> \
  --parent-id <target-parent-or-root> --copy-id <stable-copy-id> --json
```

将完整 JSON 输出保存为预览文件，检查选中节点、完整子树、资源、来源版本和目标版本，再提交：

```bash
factortester research reports copy-apply \
  --profile self --work-package-id <package> --branch-id main \
  --preview-file <preview.json> --json
```

`--component-id` 可重复选择互不重叠的小节或章节；`--after-component-id` 指定同级插入位置。来源位于本人另一 Profile 或工作包时，预览可指定 `--source-profile` 和 `--source-work-package-id`。复制重新编号内部节点和链接，保留完整公式、附件及来源记录，来源分支不变。

预览后来源或目标版本变化会拒绝提交，应重新预览。若已经写入 HEAD，但登记或 Git 步骤中断，按错误回执的 `--submission-sequence` 重试同一预览，恢复收尾步骤而不重复插入。最终通过 `branch-upload` 发布整合后的目标分支。

正文更新时间取当前分支的内容版本时间；同步时间与下载时间不作为正文更新时间。
