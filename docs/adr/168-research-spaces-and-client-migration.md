# ADR-168：研究空间保持逻辑对象，不引入真实文件夹

## 状态

已接受（2026-10-25）。

## 审计结论

当前 `research_workspaces` 是 SQLite 行：

```text
workspace_id
owner
kind
title
created_at
updated_at
deleted_at
+ ResearchConfiguration
```

它没有独立文件目录。因子源码工作区是另一概念，继续使用真实文件目录；研究空间不是源码工作区。

## 决策

研究空间保持逻辑对象：

- 身份由 workspace_id 决定；
- 内容由 ResearchConfiguration / RunSpec 引用决定；
- 不创建 `research-spaces/<id>/` 之类的活文件夹；
- 需要离线导出时生成一次性归档，不从文件夹反向推导对象身份；
- CouchDB 只保存可同步对象和报告，不把研究空间变成文件树。

## 原因

真实文件夹会引入：

- 与 SQLite/PostgreSQL 的双权威；
- 跨服务器路径、权限、删除和孤儿目录问题；
- 与 CouchDB 文档身份冲突；
- Swift/网页客户端需要同时理解路径和对象 ID；
- 归档/移动/重命名破坏引用。

## Swift 与旧报告迁移

- Swift 客户端改为通过 API 读取 `report_ref` / object ref，不拼接本地 artifact 路径；
- 公网旧报告迁移为 ReportDocument + 内容寻址附件；
- 迁移期提供只读兼容投影，但不得继续写旧路径；
- 研究空间只迁移身份与配置引用，不迁移文件树。

## 回滚

迁移期保留旧报告只读导出；CouchDB 读取失败关闭，不双写。
