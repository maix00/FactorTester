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

`FACTORTESTER_LAN_ADDRESS` is projected into the Manager as an authoritative
display address. This prevents the home page from advertising Docker bridge or
loopback addresses that another LAN device cannot use.

## Local setup

1. Copy `server.env.example` to
   `~/Library/Application Support/FactorTester/server-docker/server.env` and
   replace every example path/address. Stop any host-native Manager before the
   Docker stack claims canonical ports `7998/7997`.
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
