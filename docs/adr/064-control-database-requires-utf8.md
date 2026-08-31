# ADR 064：PostgreSQL 控制数据库必须使用 UTF-8

## 状态

已接受，2026-08-13。

## 背景

FactorTester 在共享 PostgreSQL 控制面保存用户名、组织、层级标签、Profile 元数据、设备名称和客户端描述。第一套远程集群以 `SQL_ASCII` 初始化，psycopg 因此把文本列返回为 bytes，破坏了账户匹配、超级管理员授权、Manager 身份投影和设备白名单注册，也让非 ASCII 组织/设备文本缺少数据库级校验。

## 决策

- 每个 FactorTester 控制数据库必须使用 PostgreSQL `UTF8` 编码。
- 初始化用 `ENCODING 'UTF8' TEMPLATE template0` 创建数据库，不继承集群默认 template 的不合适编码。
- 已存在且非 UTF-8 的控制库在启动时拒绝。
- 运行时连接在读取/写入身份数据前拒绝非 UTF-8 控制库；应用不得把任意 bytes 静默解码来替代正确编码。
- 既有 `SQL_ASCII` 部署通过一致性 dump 迁移到 UTF-8 数据库；旧库和 dump 在新的账户、设备和跨服务器认证检查通过前保留。

## 后果

所有 Manager 返回的文本值一致为字符串，中文组织、层级、Profile、浏览器和设备标签由 PostgreSQL 校验。错误配置会给出明确的运维错误，而不是误导性的登录失败或 `b'...'` 账户身份。
