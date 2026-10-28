# FactorTester server container

This Compose module runs one FactorTester server identity as two cooperating
containers:

- `wireguard` owns the server's private key, tunnel interface, and published
  host ports;
- `manager` shares that network namespace and owns Manager 7998, artifact data
  plane 7997, and the loopback-only test services that Manager starts.

By default this local/intranet deployment also starts the checked-out `feat`
service on port `7999` after Manager readiness. The fixed service is managed
through the 7998 control plane and is not a separately published host port.
The public deployment has a different fixed contract: its immutable `main`
service runs on internal port `8000`, also behind Manager 7998.

The native Swift client must use a different key and tunnel address. Dynamic
test ports are deliberately not published by Compose; cross-host requests go
through Manager 7998.

The host-side address agent continuously discovers the active physical LAN
address and publishes a short-lived snapshot under `FACTORTESTER_STATE_ROOT`.
Manager reads that snapshot for every heartbeat and derives the client-facing
7998/7997 endpoints from it. Never put a fixed LAN IP in `server.env`.

If the host address cannot be confirmed, Manager stops renewing its federation
lease instead of retaining an old IP or advertising a Docker/WireGuard address.
The public deployment has a separate stable-public-endpoint contract.

## Local setup

1. Copy `server.env.example` to the deployment state directory and replace the
   example paths and WireGuard values. Do not add a host LAN IP. Stop any
   host-native Manager before the Docker stack claims canonical ports
   `7998/7997`.
2. Store each server-specific WireGuard configuration as a `*.conf` file in
   `FACTORTESTER_WIREGUARD_CONFIG_DIR`; use mode 0700 for the directory and
   0600 for every file. One interface is sufficient initially. A future
   separate PostgreSQL tunnel is added as a second configuration with a
   non-overlapping address and route.
3. Verify the public Manager certificate SHA-256 fingerprint out of band and
   store its public CA/certificate at `FACTORTESTER_FEDERATION_CA_SOURCE`. It is
   mounted read-only; never disable TLS verification for federation traffic.
4. Add the new public key and tunnel `/32` to the public WireGuard hub. Add the
   same tunnel `/32` to PostgreSQL `pg_hba.conf`; do not open PostgreSQL to a
   changing public Internet address.
5. Validate and start the stack:

   ```bash
   export FACTORTESTER_DOCKER_ENV_FILE="$HOME/Library/Application Support/FactorTester/server-docker/server.env"
   scripts/server/factortester_container.sh config
   scripts/server/factortester_container.sh build
   scripts/server/factortester_container.sh up
   scripts/server/factortester_container.sh status
   scripts/server/factortester_container.sh port
   ```

6. Verify `http://<Mac-LAN-IP>:7998`, PostgreSQL through the tunnel, peer
   control/data access on `<container-WireGuard-IP>:17998/17997`, and
   authorized client data access on 7997.

The address detector supports macOS, Linux, and Windows without fixed interface
names. The current Bash lifecycle starts it for this macOS/Linux Compose entry;
a Windows deployment launcher runs the same Python agent in foreground/service
mode and uses the same snapshot contract.

`up` and `restart` never build or pull an image. Run `build` explicitly only
after changing the Dockerfile or dependency lock file. Ordinary source edits
use the mounted worktree and, when enabled, hot reload without image activity.

The local `.settings` should include the server-owned `management_access`
declaration from `deploy/local.settings.json`. It publishes the `ft-local-1`
Docker Context and the digest-checked `factortester-docker-v1` helper. A new
administrator device can discover this through `factortester-manager server
access`; it must provide its own Docker Desktop authentication and explicitly
review any downloaded helper before running it.

The staging deployment uses its own `FACTORTESTER_SERVER_ID` and state root.
Do not point two running Managers at the same state directory or advertise the
same server identity. At cutover, stop the host-native Manager first, then set
the production identity/state root and formal host ports before starting the
Compose stack.

The Manager binds `17998/17997` only to `FACTORTESTER_FEDERATION_LOCAL_ADDRESS` inside the
shared WireGuard network namespace. Compose never publishes those ports on the
host; public/LAN clients continue to use only 7998/7997.

`restart: unless-stopped` restores both containers when Docker Desktop starts.
Running `down` is an explicit stop and prevents a surprise server restart.

## Failure behavior

The WireGuard health check verifies only that the interface is configured. It
does not require a current handshake or PostgreSQL connection. Consequently a
remote outage leaves the LAN Manager available; database-backed requests show
their normal degraded/error response and recover after connectivity returns.

## Mount boundary

The Manager needs the Git common repository, stable Manager worktree, runtime
`.settings` file, publication root, and the existing application data root at
the same absolute paths used on the host. Set `FACTORTESTER_RUNTIME_DATA_ROOT`
to the directory referenced by `.settings` for SQLite, source data, caches, and
logs. That directory is mounted explicitly; the broader GTHT parent directory
is not exposed. The settings file remains read-only. This lets `git
worktree list` resolve current and future issue worktrees without exposing the
Docker socket. The application container receives those mounts; the
WireGuard sidecar receives only its configuration directory. The application
does not mount any tunnel private key.

The application image contains the Linux runtime and pinned dependencies, not
a detached source copy. Manager imports from `FACTORTESTER_REPO_ROOT`, whose
real `.git` worktree marker makes the running source revision explicit. Source
edits do not rebuild the dependency image; a deployment switches revision by
changing or updating the mounted worktree.

## Development hot reload

Set `FACTORTESTER_HOT_RELOAD=1` only for a local feature or issue deployment.
The container watches Python files in the mounted `FACTORTESTER_REPO_ROOT` and
restarts the Manager subprocess through its normal shutdown path after a short
debounce. The WireGuard container and dependency image remain running. Web
assets are read from the mounted worktree and require only a browser refresh.

The public `main` deployment keeps hot reload disabled. It changes source only
through an explicit Git/image version and restarts `factortester-public`, so an
uncommitted filesystem edit cannot silently alter the public service.

## Public-node variant

The public deployment is intentionally two business containers, each with a
different embedded WireGuard identity:

- `factortester-public` runs Manager 7998, artifact 7997, and one
  Manager-owned `main` service on internal port 8000;
- `postgresql-control` owns PostgreSQL, its data volume, and a database-only
  tunnel that is never granted to Swift clients.

The FactorTester Manager arguments include `--server-role main --fixed-port
8000 --fixed-branch main`. Compose must not publish port 8000, and the security
group must not open it or TCP 5432. Same-host database traffic uses a private
Docker network; remote authorized server nodes use the PostgreSQL container's
separate WireGuard UDP listener. Feature and issue worktrees remain local-node
capabilities and all access to public port 8000 is proxied by Manager 7998.

## TR Bundle 清单与接入包（可选停机切换）

`compose.bundles.yaml` 是显式启用的覆盖配置；本次代码不会自动改动运行容器。
平台公共契约包为 `traderesearch-data` / `traderesearch_data`。每个 Bundle 自己维护并发布
接入代码 wheel、`bundle.json` 和测试，平台不复制一份具体数据格式解析器。

- `TR_SOURCE_BUNDLES_HOST_ROOT`：已安装 Bundle 的清单目录，每个子目录一个 `bundle.json`。
- `TR_BUNDLE_PACKAGES_HOST_ROOT`：已安装并验证的接入包目录，由安装步骤准备；不是任意下载目录。
- 两个目录分别只读挂载到 `/opt/traderesearch/source-bundles` 和 `/opt/traderesearch/bundle-packages`。
  目录必须存在，不允许 Compose 自动创建空目录后悄悄启动。
- 数据卷与凭据继续单独管理；清单不能声明权限，也不能把用户电脑源激活到服务器。
- 公共接口与运行时由平台镜像提供。公网镜像构建复制 `traderesearch_data`，内网运行使用挂载
  checkout 的同一接口。接入包使用同版本接口，不能另建平台 registry。

切换前先在目标 checkout 只读盘点（不会导入 Bundle 接入代码、读取行情或迁移数据库）：

```sh
python -S -m sources.inventory --root sources --limit 100
python -S -m sources.inventory --root "$TR_SOURCE_BUNDLES_HOST_ROOT" --limit 100
```

比较 member_ref_sha256、Bundle/member 记录和产品绑定；翻页核对全部记录。输出中的
`runtime_status=not_validated` 不能解释为可执行。随后核对包版本、源代码/映射、数据可读性、
产品与用户分类绑定及备份，再通过原发布入口停机切换；在基础 Compose 文件之外显式加入
`compose.bundles.yaml`。本说明不是 push、重启或部署回执。

清单热缓存只缓存元数据；安装变化通过显式 refresh 或进程重启生效，不每次业务读取扫描目录。
数据本身的静默更新和实时流由成员 update_policy 与源适配器处理，Bundle 代码版本不等于数据版本。
当前内置 Local 行情激活仍沿用现有实现，历史规则成员的执行切换、客户端 manifest 切换及
来源包外移尚未完成；本覆盖文件不自动完成这些迁移。
