# Public host unresponsive during a heavy build

Symptoms observed:

```text
TCP 22 accepts, but SSH banner times out
HTTPS times out
ICMP is blocked by the provider
ECS instance still reports Running
```

Likely cause: the 3 GiB Nautilus wheel build saturated memory/CPU while
CouchDB and the public app stayed resident. Do not start another build.

Recovery:

1. In the Aliyun ECS console, open Workbench/VNC for the instance.
2. Run: `sudo docker rm -f nautilus-wheel-build`.
3. Check: `free -h`, `df -h / /data`, `sudo docker ps`.
4. Restart the public service if its container stopped.
5. Verify `/app` and the health endpoint before any further build.

Prevention:

- Never run the wheel builder without checking capacity and stopping/deferring
  other heavy jobs.
- Prefer a separate builder host; the public host should only pull a finished
  wheel.
- Keep the 3 GiB limit and codegen-units=16; monitor memory while building.

## Hard rule after the 2026-10-25 outage

The public app host must **never** run the Nautilus wheel builder. The builder
now refuses when it detects the public app container, or when MemAvailable is
below 5 GiB, unless `NAUTILUS_BUILD_ALLOW_SHARED=1` is set explicitly. Build on
the intranet builder and copy only the finished wheel to the public release.

## 2026-10-25 recovery result

The ECS instance was rebooted from the console. PostgreSQL initially failed
with `Address already in use` because the standalone CouchDB container had
taken its static `172.30.185.3` address. CouchDB was recreated on the same
volume with a pinned `172.30.185.5`; PostgreSQL then started healthy.

Final state: app, PostgreSQL, CouchDB and RabbitMQ healthy. The abandoned
wheel build container was removed. The build script now refuses to run while
the public app container exists or when MemAvailable is below 5 GiB.

## 2026-10-25 repeat outage

Cause: a manual Nautilus wheel build was started with a 4 GiB cgroup while
CouchDB and the app were restarted during the build to shorten downtime. The
combined memory pressure made the host unresponsive; the container was not
OOM-killed (exit 255 after host reboot). This was not disk exhaustion.

Recovery: rebooted the instance, removed `nautilus-wheel-build`, restarted
CouchDB/app/RabbitMQ, and pinned PostgreSQL to `172.30.185.6` because RabbitMQ
had taken `.3` during the reboot.

Rule: never start a public wheel build manually. Use the guarded builder only,
and if a maintenance window is unavoidable, keep CouchDB and the app stopped
for the whole build. Do not restart services mid-build.
