# Issue 443 handoff state

## Complete

- Manager no longer starts sidecar/IPC/socket daemon.
- Celery planning + execution dispatcher; RabbitMQ outbox.
- Real Nautilus strategy Job through Celery, CouchDB Job report, PostgreSQL report_ref.
- Nautilus Job retry from frozen execution plan.
- Job test report CouchDB migration 307, verification 427/0.
- Research Report CouchDB migration: 144 docs, 1265+ attachments, projection/index.
- Research Report CouchDB read-through flag + Agent manifest/Markdown (144/144 verified, 1 empty report).
- Research Report operation API: chapter move, component move/insert/remove, atomic batch, projection/index/chapter hash sync, CouchDB `_rev`/409.
- Product-group/factor/strategy CouchDB migration and read/write-through flags.
- CouchDB authority readiness: intranet true, public true.
- Keycloak OIDC login/logout, account import/backfill/dual-read, permission subjects, admin console permissions.
- Full server tests: 1505 passed / 2 skipped.
- Manager Web tests: 86 passed.
- Web Research Report editor (`?edit=1`): chapter insert/move/remove and component insert/move/remove.
- Swift uses the same WebView editor and has native operation API methods.
- CLI `research report-operation` and `report-document`.
- CouchDB authority readiness: intranet and public both `ready: true`.

## Blocks requiring explicit authorization / external build

- Public publication requires `FACTORTESTER_PUBLISH_AUTHORIZED=1` and the `main`
  worktree; this branch is `fix/issue-443-nautilus-bridge`.
- Linux Nautilus 2.0.0rc8 runtime has no wheel and no build toolchain on the
  public host.

## Not complete

- Public server does not run the latest authority code.
- Authority mode is not enabled in production.
- Legacy SQLite/JSON/mirror paths still exist.
- Strategy shares/authorized relations remain SQLite.
- Web/Swift do not call the Research Report operation API.
- Research Report edit UI absent.
- Public Python 3.13 + Nautilus runtime is blocked (no Linux wheel, no Rust/Cython).
- TradeResearch service/package/database rename incomplete.

## Safe next steps

1. Deploy current worktree to public and run:
   `scripts/migrations/smoke_couchdb_authority.py`
2. Enable `TRADERESEARCH_COUCHDB_AUTHORITY=1` on intranet, observe 7 days.
3. Enable on public after deployment.
4. Wire Web/Swift edits to `/api/research-reports/<id>/operations`.
5. Migrate strategy shares, then remove legacy paths with
   `scripts/migrations/purge_legacy_authority_paths.py --confirm`.
6. Build a Linux Nautilus 2.0.0rc8 runtime before claiming public Nautilus.

## Rollback

- Unset `TRADERESEARCH_COUCHDB_AUTHORITY` -> SQLite/JSON/mirror.
- `TRADERESEARCH_AUTH_MODE=legacy` -> old password login.


## Public deployment (2026-10-25)

- Production revision `ae67b22a0f98b37454bc8a8ef03682eb7b1a4162` verified.
- Public CouchDB authority enabled; app-level smoke: 15 product groups,
  126 factor-family documents, 144 Research Reports.
- Root disk was 90% full and an in-place Docker build crashed the host.
  Cleaned Docker images/build cache and journals; added
  `scripts/server/check_public_build_capacity.sh`.
- Public image builds now use BuildKit inline cache; PostgreSQL container and
  data were preserved. The fixed-service symlinks under
  `/opt/factortester-container/services` must point to existing release dirs.


## Public root disk

- `/opt/factortester-container/state/job-index.sqlite` is 4.1G because
  `control_events` holds ~650k rows (about 4.0G of that file).
- `/opt/factortester-container/state-debug` was a stale duplicate of the
  same 4.1G index; it was not mounted or open and was removed, freeing 4.3G.
- Docker images/build cache and journals were pruned separately.
- Root disk after cleanup: 21G free on a 40G volume.
- Future work: add a bounded retention policy for `control_events`; do not
  delete event history while a peer cursor still needs it.


## Public state storage move (2026-10-25)

- `/data` is a separate 60G ext4 volume; `/` is only 40G.
- Moved the live Manager state (`job-index.sqlite`, transfers, releases,
  logs) from `/opt/factortester-container/state` to `/data/state` and
  updated `FACTORTESTER_STATE_ROOT`.
- Removed the old 4.1G state copy and the stale `state-debug` copy.
- Root filesystem is now 13G used / 25G free; `/data` has 31G free.
- The 4.1G `control_events` history now lives on `/data`; use
  `scripts/server/prune_control_events.py` (dry-run by default) if it grows.


## Public capacity check (2026-10-25)

```text
root_free_gb=24 data_free_gb=30 mem_available_mb=3592
job_index_gb=4 control_events=650492
```

`scripts/server/check_public_capacity.sh` exits non-zero below
10G root, 10G `/data`, or 1024MB MemAvailable.

## React shell i18n and local containers (2026-10-25)

- React shell now uses i18next/react-i18next with shared `tr.language`.
- Desktop Ant Design locale follows the same language; mobile uses native
  language select to avoid shipping Ant Design.
- Local Docker cleanup: removed the duplicate stopped `ft-couchdb-b` container;
  kept `ft-couchdb`, `ft-rabbit`, `ft-keycloak` and their volumes.

## Local intranet React-shell test

Run from the integration checkout:

```bash
./scripts/server/start_local_manager.sh
```

The Manager binds `0.0.0.0:8770`; open `/app` on the LAN address printed at
startup. This instance uses `/tmp/ft-manager-state` and `/tmp/ft-manager-data`
so it does not touch production state. Verified: `/app` returned 200, desktop
Dockview rendered, mobile rendered 5 bottom tabs, and the page list loaded.

Health check for that instance:

```bash
./scripts/server/check_local_test.sh
```

It verifies `/app` returns 200 and reports the three local dependency
containers (`ft-couchdb`, `ft-rabbit`, `ft-keycloak`).
