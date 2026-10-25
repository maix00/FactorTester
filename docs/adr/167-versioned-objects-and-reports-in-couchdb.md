# ADR-167：版本化对象与报告统一存入 CouchDB

## 状态

已接受，迁移进行中（2026-10-25）。

## 决策

- PostgreSQL 继续保存用户、权限、Job/Run/Attempt 状态、调度 outbox 等关系数据。
- CouchDB 保存需要跨服务器复制的版本化对象：
  - FactorVersion
  - StrategyVersion
  - ReportDocument
  - ReportAttachment
- 同一对象只能有一个权威来源：进入 CouchDB 后，PostgreSQL 只保留引用/查询投影，不再独立编辑正文。
- 跨服务器复制使用 CouchDB Replication，不使用 RabbitMQ 承载对象复制。
- RabbitMQ 只承载 Job plan/execute 调度。

## 文档身份

```text
factor:v2:<digest>
strategy:v2:<digest>
report:<report_id>:<revision>
```

文档包含：

```text
schema_version
kind
owner_ref
created_at
source_refs
content_sha256
attachments[]
```

附件采用内容寻址名称：

```text
<sha256>.<ext>
```

## 报告存储简化

目标：

- 一个 ReportDocument 取代当前多份 manifest/receipt/summary/HTML 目录副本；
- HTML、CSV、tearsheet 作为附件，不再在多个 SQLite/artifact 路径各存一份索引；
- PostgreSQL 只保存 `report_ref` 与 Job 关联；
- Job 结果读取通过 report_ref 解析，不再拼接复杂 artifact 路径；
- 保留内容哈希用于校验，不以重复索引表达版本。

## 冲突

- CouchDB 冲突按对象类型裁决；
- 因子/策略版本不可变，冲突保留双方 revision，由业务选择有效版本；
- 报告文档允许 owner 修订，冲突进入待裁决队列，不自动覆盖；
- 任何裁决写入审计记录。

## 迁移

1. 定义文档 schema 与内容哈希；
2. 导出当前报告/因子/策略版本；
3. 双读校验，PostgreSQL 仅作投影；
4. 切换写入 CouchDB；
5. 删除旧报告路径与重复索引；
6. 开启多服务器 Replication。

## 回滚

迁移期保留只读导出；CouchDB 不可用时 Job 结果读取失败关闭，不回退到旧双写。
