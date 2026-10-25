# Local multi-port Celery/RabbitMQ test harness

This harness runs one RabbitMQ broker, one dispatcher, and two target-scoped
workers for the `local-docker` deployment: one bound to service port 8000, one
to 8001.  The dispatcher owns the shared outbox -> broker loop; workers never
publish.

It is a development/test topology, not a production deployment.

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

The target queue names are not a substitute for a shared Job database. A worker
on another server must never be given this server's Job DB path.
