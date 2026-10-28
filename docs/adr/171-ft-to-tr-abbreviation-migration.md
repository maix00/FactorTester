# ADR-171：FT 缩写迁移为 TR

## 状态

已接受（2026-10-25），分层执行。

## 原则

- `FT` 不再代表平台名。
- 用户可见缩写迁移为 `TR` / `TradeResearch`。
- `FactorTester` 保留为因子测试子能力。
- 不一次性替换所有内部标识；先别名，后迁移，再删除。

## 分层

### 1. 用户可见

```text
FTClient -> TradeResearch / TRClient
FTManager -> TradeResearch Manager / TRManager
FT 首页 -> TradeResearch
FT 文档 -> TradeResearch 文档
```

已开始：

```text
<title>TradeResearch</title>
sidebar brand TradeResearch
```

### 2. JS/CSS 全局

```text
FTUI -> TRUI
FTManager -> TRManager
FTHighcharts* -> TRHighcharts*
ft-* CSS class -> tr-* class
```

迁移期必须：

```js
window.TRUI = window.TRUI || window.FTUI;
window.FTUI = window.TRUI;
```

CSS 同时保留旧 class 一个版本：

```css
.tr-panel, .ft-panel { ... }
```

### 3. App bundle / 资产

```text
FTClient.app -> TradeResearch.app
FTClient.dmg -> TradeResearch.dmg
com.example.FTClient -> com.example.TradeResearch
```

必须提供：

- 旧下载 URL 重定向；
- 旧 bundle 迁移提示；
- 回滚安装包。

### 4. 服务/包/环境变量

```text
factortester-manager -> traderesearch-manager alias
FACTORTESTER_* -> TRADERESEARCH_* dual read
```

包名和服务名延后。

### 5. 数据库/队列/复制

```text
SQLite/PostgreSQL 表名
RabbitMQ exchange/queue
CouchDB database/document ID
```

不直接改名；需要双读、双队列绑定、复制完成和回滚方案。

## 禁止

- 全局字符串替换 `FT`；
- 删除旧 JS 全局/CSS class 而不保留 alias；
- 在旧客户端未迁移前删除 `FTClient` 下载路径；
- 同时写两套品牌状态。

## 验收

- 用户界面无 `FTClient`/`FT ` 品牌残留；
- 旧入口仍可用；
- 新入口测试通过；
- 回滚路径存在。
