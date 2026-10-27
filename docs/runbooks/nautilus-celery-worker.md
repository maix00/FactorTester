# Nautilus Celery worker runbook

## Required environment

```text
FACTORTESTER_BROKER_URL=amqp://...
FACTORTESTER_JOB_QUEUE=factortester.jobs
FACTORTESTER_JOB_DB=/data/sqlite/research-jobs.sqlite
FACTORTESTER_DEPLOYMENT_ID=<deployment>
FACTORTESTER_SERVICE_PORT=<port>
FACTORTESTER_NAUTILUS_CATALOG_ROOT=<catalog root>
FACTORTESTER_COUCHDB_URL=http://...
FACTORTESTER_COUCHDB_DB=ft_objects
FACTORTESTER_COUCHDB_USER=...
FACTORTESTER_COUCHDB_PASSWORD=...
```

The `CACHE_DB_PATH` in the worker wrapper must point at the factor library
used by `factor:v2` records; it is separate from the Job database.

## Start

```bash
celery -A server.jobs.dispatch.celery_app:app worker \
  --hostname "nautilus@%h" \
  --pool=solo --concurrency=1 \
  --prefetch-multiplier=1 \
  --max-tasks-per-child=1 \
  --loglevel=INFO
```

Queue binding is `factortester.jobs.<deployment_id>.<service_port>`.

## Health checks

```text
GET /api/dispatch/overview
-> workers / outbox / dead
```

RabbitMQ:

```bash
rabbitmqctl list_queues name messages consumers | grep factortester
```

## Known failure: empty report_ref

If a Job succeeds but `report_ref` is empty:

1. check **all** workers on the queue;
2. stop any stale worker started without CouchDB env;
3. ensure only correctly configured workers consume the queue;
4. rerun the Job or retry the Nautilus Job from its frozen plan.

A stale worker without CouchDB env can consume the message and produce a
valid engine result with no report.

## Retry

```text
Nautilus Jobs retry from the frozen execution_plan.
Legacy backtests without a plan return 409.
```

## Shutdown

Stop workers gracefully; queued outbox rows remain durable.  Do not delete
`/data/job-results` until CouchDB report verification passes.


## Isolated real-worker acceptance

GTHT declares `celery==5.6.3`. Build both alpha and the composed Nautilus extension
before validating a changed gitlink. Use dedicated localhost RabbitMQ/CouchDB
instances, an existing real staged T/TL manifest, and a new temporary output root:

```bash
conda run -n GTHT python -m tests.benchmarks.verify_native_celery_job \
  --manifest /tmp/real-t-tl/manifest.json --root /tmp/native-job-check \
  --broker "$LOCAL_ACCEPTANCE_BROKER_URL" --couch-url "$LOCAL_ACCEPTANCE_COUCH_URL" \
  --credentials-file /tmp/local-acceptance-credentials.json --family-mode mixed
```

The credentials file contains `username`/`password` for the dedicated local
CouchDB; restrict its permissions. Never point this tool at production or use
production credentials. `group` and `threshold` modes verify separate Jobs.
The tool starts/stops only its worker, removes only its unique queue, retains
Job DB/reports/receipt, and verifies the terminal Job plus report attachment
hashes. RabbitMQ/CouchDB lifetime remains the caller's responsibility. It uses
normal broker delivery and the real default executor, not eager Celery or mocks.
It validates frozen-plan execution, not HTTP authoring/planning or exchange rules.
