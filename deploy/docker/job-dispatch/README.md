# Local multi-port Celery/RabbitMQ test harness

This harness runs one RabbitMQ broker, one dispatcher, and two target-scoped
workers for the `local-docker` deployment: one bound to service port 8000, one
to 8001.  The dispatcher owns the shared outbox -> broker loop; workers never
publish.

It is a development/test topology, not a production deployment.

Before starting, run the target preflight inside the worker image (it checks broker,
deployment/port, writable WAL directory, and executor availability):

```bash
python -m server.jobs.dispatch.preflight --check-executor --json
```

```bash
cp deploy/docker/job-dispatch/env.example deploy/docker/job-dispatch/.env
# edit .env: broker password, job DB path, state/data roots
docker compose \
  --env-file deploy/docker/job-dispatch/.env \
  -f deploy/docker/job-dispatch/compose.yaml \
  up --build
```

Routing:

```text
factortester.jobs.local-docker.8000
factortester.jobs.local-docker.8001
```

The two workers share one broker but never the same queue. A worker also
checks the message target before claiming, so a misbound consumer returns
`wrong_target` without touching the Job database.

Requirements:

- the base image must contain this checkout at `/opt/factortester/app`;
- `FACTORTESTER_JOB_DB` must point at the same SQLite Job database used by the
  local Manager;
- RabbitMQ management is bound to loopback only;
- `FACTORTESTER_NAUTILUS_EXECUTOR` must resolve to the approved Nautilus Job
  executor; otherwise tasks fail before claiming.

Inspect or requeue outbox rows without connecting to the broker:

```bash
python -m server.jobs.dispatch.cli status
python -m server.jobs.dispatch.cli show <job_id> <attempt>
python -m server.jobs.dispatch.cli retry <job_id> <attempt>
```

`retry` only accepts failed/dead rows and resets attempts; it does not bypass a
worker capability check.

One-host public acceptance (existing app image, isolated DB, fake executor):

```bash
FACTORTESTER_TEST_RELEASE_SHA=<full-sha> \
FACTORTESTER_TEST_DEPLOYMENT=public-test \
FACTORTESTER_TEST_PORTS="8000 8001" \
bash scripts/server/deploy_dispatch_test.sh
```

This starts an isolated RabbitMQ container, two target workers in the existing
app container, and runs the probe.  It does not touch the production Job DB or
Manager configuration.

Acceptance probe (isolated DB; the worker executor must accept the probe):

```bash
python scripts/test/job_dispatch_smoke.py \
  --db /tmp/dispatch-smoke/jobs.db \
  --broker amqp://factortester:***@127.0.0.1:5672// \
  --deployment local-docker --port 8000 --port 8001
```

It creates one queued probe per port, dispatches, and waits for terminal Job
state.  It is not a Nautilus performance run and must not be pointed at the
production database.

The target queue names are not a substitute for a shared Job database. A worker
on another server must never be given this server's Job DB path.

Shared input prerequisites: use the same host `FACTORTESTER_STATE_ROOT` and
Manager `FACTORTESTER_SERVER_ID` (control authority), `TR_EXECUTION_NODE_ID`
(execution installation identity), and `TR_SHARED_STORAGE_ID` (kernel/backing-file
cache domain) in the colocated business and dispatch Compose projects. Independent
nodes use distinct node IDs, including two independent nodes on one physical host.
Only processes sharing the actual kernel, backing files and trusted cache may
reuse a storage-domain ID. They resolve the cache to the same `shared-columnar`
directory with one resource policy; the cache domain does not identify a source. Container users must have
compatible numeric UID/file permissions; do not make the cache world-writable.
Workers must not mint a separate Manager identity. Client-owned sources remain
isolated and are not uploaded by this configuration.

This prepares cross-container cache reuse; it does not implement normalized
result caching, queue-aware lifetime management, or aggregate host RAM admission.
The cache byte limit bounds cached files, not process RSS. Docker Desktop
containers and native macOS processes do not share one kernel page cache.
See ADR-187 for pending work and acceptance; no containers are started by this change.

These Compose projects still describe local execution. They do not enable remote
workers: remote nodes must use authenticated Job/input/result transport through
the existing authority and queue, never mount a Manager SQLite file. Bundle
installations differ by node even when their package/version is equal. RunSpec
Bar requirements are portable; exact installation selection belongs to the
ExecutionPlan. See ADR-188 for compatibility and remaining routing work.
