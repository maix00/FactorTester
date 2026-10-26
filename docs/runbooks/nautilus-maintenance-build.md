# Nautilus wheel maintenance build

The public app host must not build while CouchDB and the app are running.
When no separate x86 builder is available, use a short maintenance window:

1. Confirm `/data` has at least 20 GiB free. Run `scripts/server/check_public_build_capacity.sh`.
2. Stop `factortester-public-factortester-public-1` and `factortester-couchdb`;
   leave PostgreSQL/RabbitMQ running.
3. Confirm `MemAvailable` is at least 6 GiB.
4. Use a persistent builder image. A 4 GiB cgroup with fat LTO is not enough
   for `nautilus-pyo3` linking; use 5 GiB and thin LTO:
   `--memory=5g --memory-swap=5g --cpus=3`,
   `CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16`,
   `CARGO_PROFILE_RELEASE_LTO=thin`, `CARGO_BUILD_JOBS=2`.
5. Always restart CouchDB and the app in a `trap`/watcher, whether the build
   succeeds or fails.
6. Smoke-test the wheel inside the public runtime image before using it.

This is a controlled downtime, not a background build on a live host.

## Disk safety

Rust `target/` trees are disposable and have reached ~100 GiB on a developer
host.  Never leave them in the repository across builds.

- Local wheel builds run `scripts/server/check_local_build_capacity.sh` and use
  an external target directory (`NAUTILUS_TARGET_CACHE`) that is deleted on
  exit, with release debug symbols and incremental compilation disabled.
- Public deploys use `scripts/server/check_public_build_capacity.sh` and may
  reclaim only disposable state with
  `scripts/server/prune_public_build_artifacts.sh`; tagged rollback images are
  never pruned.
- A build that would leave less than the configured free-space floor must fail
  before it starts, not exhaust the host.
