# 远端 PostgreSQL 控制库

## 端口与职责

- 本机 `127.0.0.1:2222` 若存在，只是 SSH 转发/代理入口，用于进入远端主机；它不是远端业务端口，不参与普通用户或服务器之间的业务通信，也不应写进任何 Manager/PostgreSQL URL。
- PostgreSQL：远端 `5432/TCP`，只允许本机服务器的固定公网 IP 或 VPN 网段访问。
- Manager：每台服务器的 `7998/TCP`，负责登录、权限、任务元数据、节点路由和签名票据。
- 数据面：每台服务器的 `7997/TCP`，负责实际运行节点上的源码快照、生成物和提交物传输。
- 测试服务：例如远端 `8000`，只由本机或对端 `7998` 代理访问。

本机连接远端 PostgreSQL 时只产生本机的出站连接，不需要在本机再固定开放一个数据库端口。

## 一次性初始化

在安装了 PostgreSQL 的远端服务器执行：

```bash
python scripts/setup_control_postgres.py \
  --admin-url 'postgresql:///postgres?user=postgres' \
  --app-host db.internal.example \
  --app-user factortester_control \
  --app-password '<从密码管理器读取>' \
  --env-file /etc/factortester/control-db.env
```

这里的管理员 URL 使用远端 PostgreSQL 的 Unix socket；`--app-host` 必须填写本机服务器能够访问的远端 DNS/IP。也可以把管理员 URL 换成带管理员认证的 `127.0.0.1:5432` TCP URL。脚本是幂等的，会以 `UTF8` 编码从 `template0` 创建专用数据库、创建角色并执行 schema；不会启动 7998、8000 或 7997，也不会覆盖已有应用角色密码，除非显式加 `--rotate-password`。如果同名数据库已经存在但不是 UTF-8，脚本会停止并要求先迁移，不会把用户、机构、层级或设备名称静默读成 bytes。

脚本直接写入的远端文件会被远端三个 systemd 单元自动加载；本机 Manager 则用同一个连接串配置自己的服务环境。不要把它提交到 Git。生产环境应把连接串中的 `sslmode=require` 提升为 `verify-full`，并配置 PostgreSQL 服务器证书与 CA。

## SQLite 控制数据迁移

初始化 schema 后，在仍能读取旧 SQLite 的那台服务器执行一次迁移。迁移默认只做 dry-run；确认数量后再加 `--apply`。`--apply` 会先用 SQLite Online Backup 生成副本，然后以只读方式读取 SQLite：

```bash
python scripts/migrate_sqlite_control_to_postgres.py \
  --source-db /data/sqlite/unifieddata.sqlite \
  --client-root "$FACTORTESTER_CLIENT_ROOT"

python scripts/migrate_sqlite_control_to_postgres.py \
  --source-db /data/sqlite/unifieddata.sqlite \
  --client-root "$FACTORTESTER_CLIENT_ROOT" \
  --database-url "$FACTORTESTER_CONTROL_DATABASE_URL" \
  --apply \
  --backup-path /data/sqlite/backups/unifieddata.pre-control-migration.sqlite
```

迁移报告会列出用户、机构、层级、配额、Profile 数量和 SQLite 因子源码元数据数量。任务执行事实、队列、生成物索引仍留在各自服务器的 SQLite；SQLite 不是 PostgreSQL 备份。源码正文也不会直接进入 PostgreSQL，必须先绑定 Git 完整 commit SHA/content hash，再通过 7997 的源码/生成物数据面传输。

## 数据边界

PostgreSQL 保存跨服务器必须一致的控制数据：用户、机构、层级树、Profile 元数据、配额、服务器使用量快照，以及因子/策略源码的版本目录。源码正文不放进 PostgreSQL；它保留在 Git 仓库或内容寻址存储中，控制库记录完整 Git commit SHA、tree/blob/content hash、相对路径和存储节点。

各节点 SQLite 仍保存本机任务执行事实和生成物元数据。它不是 PostgreSQL 的备份，也不能在数据库断线时悄悄写入另一套用户/配额事实。PostgreSQL 应使用 `pg_dump` 与 WAL 备份；源码使用 Git 远端或对象存储版本；节点 SQLite 只按本机任务恢复需要单独备份。

## 源码版本

任务提交时：

1. 完整 commit SHA 是不可变版本主键，branch/ref 只用于显示。
2. 因子引用还记录 blob hash；策略/源码快照记录 tree/content hash。
3. 工作区有未提交修改时，必须先生成快照并得到 `snapshot_ref`，否则任务拒绝提交。
4. 执行节点通过 7997 获取对应版本/快照，取不到或 hash 不匹配时任务失败，不自动使用该节点当前 branch。
