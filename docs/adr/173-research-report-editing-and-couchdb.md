# ADR-173：研究报告编辑与 CouchDB 边界

## 状态

已接受（2026-10-25）。

## 背景

研究报告的插入、移动、删除、批量操作目前由本地报告工作区实现：

```text
tools/cli/release/research_reporting/authoring/
  service.py            add_branch_component / apply_branch_batch
  tree_move.py          move_component
  tree_removal.py       remove_component
  tree_model.py         copy-on-write tree snapshot
```

报告树顺序由父节点 `children` 数组决定；移动是 detach + insert after，
并校验 cycle、parent/child kind。

编辑结果随后作为完整 projection 同步到服务器：

```text
PublicResearchLibrary.sync
-> publications.json
-> mirrors/<publication_id>.json
-> index.json
-> assets/chapters/local-resources
```

CouchDB 迁移保存的是该 projection 和附件的快照：

```text
research-report:<publication_id>
  publication
  projection.json
  index.json
  attachments
```

## 决策

CouchDB 不负责报告树语义。它只提供：

- 文档 CRUD；
- `_rev` 乐观并发；
- 409 冲突；
- 附件；
- 复制；
- 冲突 revision。

插入/移动必须由报告领域代码实现，不能把“修改 children 数组”下放给
CouchDB。

## 后续写入协议

若切换 CouchDB 为编辑权威，必须新增命令 API，而不是让客户端 PUT 整份
projection：

```text
POST /api/research-reports/<publication_id>/operations
{
  "base_rev": "<couchdb-rev>",
  "op": "insert" | "move" | "remove",
  ...
}
```

服务端必须：

1. 读取当前 CouchDB 文档与 `_rev`；
2. 复用现有 tree 校验；
3. 应用操作到 projection；
4. 带 `_rev` 写回；
5. 409 时返回冲突，不静默覆盖；
6. 记录 operation/revision 审计；
7. 更新 projection/index 附件。

## 禁止

- 把 CouchDB 当作树操作引擎；
- 客户端无 `_rev` 覆盖整份报告；
- 只改 projection 而遗漏附件；
- 在冲突时 last-write-wins；
- 删除本地 git 报告工作区前未完成双读/回滚。

## 回滚

当前 CouchDB 读透开关：

```text
TRADERESEARCH_RESEARCH_REPORTS_COUCHDB_READ=0
```

恢复本地 `publications.json + mirrors` 读取。
