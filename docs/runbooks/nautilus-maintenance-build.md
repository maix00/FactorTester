# Nautilus wheel maintenance build

The public app host must not build while CouchDB and the app are running.
When no separate x86 builder is available, use a short maintenance window:

1. Confirm `/data` has at least 15 GiB free.
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
