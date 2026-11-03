# Nautilus wheel build and cache maintenance

Use `scripts/server/build_nautilus_linux_wheel.sh` on a dedicated build host or
an explicitly selected external build volume. The public application host does
not compile Rust alongside production services. Do not stop CouchDB or the app
merely to make room for a build. The former production maintenance-build recipe
is retired; source history retains it for incident analysis.

Finished wheels and Cargo objects have different identities and lifetimes.
Verify the checksummed finished artifacts first. Otherwise retain compatible
Linux Cargo dependencies for incremental compilation; macOS arm64 objects cannot
be used as Linux amd64 objects. An adapter-only change can reuse a checksummed
standalone alpha wheel only after all other source inputs are equal.

The default is `NAUTILUS_INCREMENTAL_ONLY=1`: missing retained Nautilus
libraries refuse a cold build. Set it to `0` only for an explicitly approved
initial build, then restore the default. Keep the existing two-CPU, 3 GiB,
single-job, no-extra-swap limits. A memory limit is not a disk limit.

Before building, agree on the allowed local footprint. For storage-constrained
clients, place Cargo registry/git/target and the source snapshot on the selected
build host or external volume via `NAUTILUS_CACHE` and `NAUTILUS_TARGET_CACHE`;
retain only verified finished wheels locally if allowed. Use a stable cache path
across release worktrees and the existing exclusive build lock. Do not create
one full build cache per checkout.

The target default budget is 6 GiB, excluding registry/git, source and finished
wheels; this may be unacceptable on a personal machine. Check all those paths,
peak staging allocations and Docker storage before starting. A capacity check
or after-build cache trim does not impose a hard disk quota during compilation.
Never clear all targets or global Docker/Xcode state as an automatic retry.
Cleanup of named generated artifacts remains a separately scoped operation;
protect current/rollback images, source, user data, databases and backups.
