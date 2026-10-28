# Public FactorTester containers

This module replaces the native public-host services with exactly two
business containers:

- `factortester-public` owns the FactorTester WireGuard identity and runs
  public Manager `7998`, public data `7997`, and loopback-only main service
  `8000`.
- `postgresql-control` owns a different WireGuard identity and PostgreSQL.

The application and database communicate on the internal `private` Docker
network. Neither `8000` nor TCP `5432` is published. Server peers use
FactorTester's WireGuard-only `17998/17997` listeners when the deployed source
revision contains Issue #184; those ports are never host-published.

## Required host ingress

Production needs TCP `7998`, TCP `7997`, UDP `51820` (FactorTester federation),
and UDP `51821` (database tunnel). Do not open TCP `8000`, TCP `5432`, TCP
`17998`, or TCP `17997` in the public security group. Only authorized server
nodes receive a database-tunnel peer; Swift clients do not.

## Optional Mihomo Dashboard

The application image pins the upstream Mihomo binary and the official
MetaCubeX dashboard. To enable it, place an owner-only `mihomo.yaml` in the
configured `FACTORTESTER_MANAGER_STATE_SECRETS_DIR` before restarting the
application container. The Manager copies it into `/state` for the
`factortester` user and forces the controller (`9090`) and mixed proxy (`7890`)
to `127.0.0.1`; TUN, LAN binding, and controller secrets are disabled. A
super-admin opens the `Mihomo Dashboard` home module and starts or stops the
process. The dashboard and its API are served through the authenticated
Manager `7998` origin, so no additional security-group ingress is required.

## WireGuard membership authority

WireGuard does not discover or distribute peers. Each server generates its
FactorTester and PostgreSQL tunnel secrets locally; only the corresponding
public keys leave that server. A cluster deployment administrator maintains a
versioned public inventory and signs it with an owner-only inventory authority.
The Manager and PostgreSQL never receive that signing secret.

Use `scripts/server/factortester_wireguard_inventory.py` to generate a local
identity, sign or verify the public inventory, and render one node's `0600`
configuration. A private/NAT node has one gateway record in each tunnel;
future nodes are added to the signed inventory rather than entered as
individual peers in web settings. Application discovery remains separate:
the configured bootstrap returns credential-free nodes, and a direct Manager
relationship is authenticated only when a task or transfer needs that node.

## Versioned deployment

Copy `public.env.example` outside the repository, replace all example values,
and restrict it and every secret to the owner. `FACTORTESTER_REVISION` must be
the full SHA of a clean checkout. The image embeds that source and disables
hot reload and service debug mode.

Use `scripts/server/factortester_public_container.sh` to validate, build,
start, inspect, back up, restore-check, and verify the deployment. `up` never
builds or pulls implicitly. A PostgreSQL outage does not stop or restart the
FactorTester container; database-backed requests degrade until the independent
database container recovers.

Run `scripts/server/publish_public_main.sh` from a clean `main` worktree for the
normal incremental publication transaction. It pushes only missing Git
objects, builds the SHA-tagged application image with Docker's layer cache,
backs up PostgreSQL, switches only the application container, and verifies both
the runtime and database restore before accepting the release. After acceptance
it retains the newest three revisions recorded as verified in
`/opt/factortester/deployments.log`; set
`FACTORTESTER_PUBLIC_RELEASE_RETENTION` to another
positive integer when more rollback depth is required. Cleanup is limited to
old `factortester-public:<40-character SHA>` tags and their matching release
worktrees. It never removes the PostgreSQL image, volumes, other projects, or
the global Docker build cache, and it never invokes `docker system prune`.

The public host does not fetch GitHub. Publication is push-driven from the
trusted local machine: the publisher transfers `main` directly to the public
bare repository through the configured maintenance SSH/Alibaba Session Manager
transport, verifies the remote SHA, and invokes the activation transaction
synchronously. The default `launch-advisor` alias does not require public TCP
22; a local `2222` forward remains an optional manual transport. Once that
single command starts, build, backup, switch, verification, rollback, and
retention do not require an operator or Agent. If the maintenance transport
fails, the currently verified release remains untouched and the same command
can be retried.

The public `.settings` also declares the non-secret operator access projection:
the `ft-public-1` Docker Context, the current SSH endpoint/profile, and the
bounded release-activation script. `factortester-manager server access` is the
only supported way for a client to discover that metadata. The CLI may download
the digest-checked scripts, but never executes them and never receives the SSH
key or Alibaba credentials. Keep the declaration synchronized with the current
public endpoint when the public address changes.

Before replacing a native PostgreSQL instance, create a custom-format dump and
retain a checksum outside the container volume. Restore it into a new named
volume, run `backup` and `restore-check`, then switch the host ports. Keep the
native dump until the container backup has itself passed a restore check.

## Rollback

Stop the two containers without deleting the named volume, restore the prior
native PostgreSQL service if required, and restart the prior Manager unit. The
deployment script's `down` command deliberately omits `--volumes`; it cannot
delete the PostgreSQL volume. Removing native releases, virtual environments,
units, or database files is a separate cleanup step after container validation.

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
