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
