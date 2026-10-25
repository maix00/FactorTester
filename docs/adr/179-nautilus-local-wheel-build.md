# ADR 179: Build Nautilus on the Linux build host

Status: accepted.

## Decision

The platform never publishes a hand-built or downloaded Nautilus wheel.
`scripts/server/build_nautilus_linux_wheel.sh` builds from the clean local
`vendor/nautilus_trader` submodule on an x86_64 Linux host and caches the wheel
by the submodule commit.

- Source transfer is incremental (`sync_nautilus_source.sh`); the cargo target
  and registry stay on the host.
- `NautilusBuilder.Dockerfile` keeps apt/Rust/maturin in a reusable image.
- Release builds pass `NAUTILUS_WHEEL_REQUIRED=1`; a missing wheel fails the
  image build instead of silently shipping the old runtime.
- `nautilus-model` exceeds 3 GiB at `codegen-units=1`; builds use 16 units,
  one cargo job and a 3 GiB container so the public app stays healthy.
- A wheel is reused only for the same local commit. A changed commit rebuilds
  incrementally; a cold builder is the only full rebuild case.

## Consequence

The first cold build is long. Subsequent Python-only changes are short;
Rust/dependency changes rebuild only the affected graph. The wheel itself is
not transferred between hosts unless a separate build host is used.
