# ADR-169：平台品牌迁移为 TradeResearch

## 状态

已接受（2026-10-25），分阶段执行。

## 决定

平台名称改为 **TradeResearch**。

`FactorTester` 保留为平台内的因子测试子能力名称，不再作为整个平台名。

不做无差别字符串替换。

## 命名分层

### 立即迁移（用户可见）

```text
UI 标题
登录页
文档标题
CLI 命令名
帮助文本
错误信息
Swift 客户端显示名
报告页眉
```

目标入口：

```text
traderesearch
traderesearch-manager
```

### 兼容期迁移（外部接口）

```text
FACTORTESTER_* -> TRADERESEARCH_*
factortester-manager -> traderesearch-manager
```

规则：

- 新名优先；
- 旧环境变量继续读取并告警；
- 旧 CLI 入口保留 alias；
- 至少跨一个正式版本再删除。

### 延后迁移（数据/基础设施）

```text
Python 包名
SQLite/PostgreSQL 表名
RabbitMQ exchange/queue 名
CouchDB database 名
数据目录名
```

原因：

- 在途 Celery 消息会丢；
- 旧客户端会断；
- 数据库重命名破坏复制和回滚；
- CouchDB 复制配置/文档 ID 可能变化。

迁移必须提供：

- 新队列与旧队列的临时绑定/消费；
- 环境变量双读；
- CouchDB 新库复制完成后再切换；
- PostgreSQL 只改显示名，不重命名表；
- 数据目录 symlink 或迁移脚本；
- 回滚路径。

## 保留 FactorTester 的位置

```text
FactorTester CLI 子命令（若指因子测试）
FactorTester 因子计算/回测子能力
历史 ADR/迁移说明
数据库历史字段
API 中语义确实属于因子测试的字段
```

## 目标

```text
平台：TradeResearch
子能力：FactorTester、Strategy Research、Reports、Jobs
服务：traderesearch-server、traderesearch-manager
```

## 禁止

- 一次性重命名数据库表；
- 直接改 RabbitMQ 队列名而不保留旧绑定；
- 同时保留两套品牌入口长期双写；
- 在未迁移客户端前删除 `factortester-*` 兼容入口。
