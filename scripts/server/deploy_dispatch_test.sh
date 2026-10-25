#!/usr/bin/env bash
# Deploy an isolated, non-production dispatch acceptance stack on one host.
# It never changes the production service DB or Manager configuration.
set -euo pipefail

APP_CONTAINER="${FACTORTESTER_APP_CONTAINER:-factortester-public-factortester-public-1}"
RABBIT_CONTAINER="${FACTORTESTER_RABBIT_CONTAINER:-factortester-job-rabbit}"
DEPLOYMENT="${FACTORTESTER_TEST_DEPLOYMENT:-public-test}"
PORTS="${FACTORTESTER_TEST_PORTS:-8000 8001}"
RELEASE_SHA="${FACTORTESTER_TEST_RELEASE_SHA:?set FACTORTESTER_TEST_RELEASE_SHA}"
ROOT=/opt/factortester-container/job-dispatch-test
RELEASE_HOST=/opt/factortester-container/releases/audit-dispatch-${RELEASE_SHA:0:12}
RELEASE_CONTAINER=/opt/factortester/releases/audit-dispatch-${RELEASE_SHA:0:12}
DB=/state/job-dispatch-test/jobs.db
BROKER="amqp://guest:guest@${RABBIT_CONTAINER}:5672//"

sudo mkdir -p "$ROOT/rabbitmq" "$ROOT/state"
if ! sudo docker inspect "$RABBIT_CONTAINER" >/dev/null 2>&1; then
  sudo docker run -d --name "$RABBIT_CONTAINER" --restart unless-stopped \
    --network factortester-public_private --user 0:0 \
    -v "$ROOT/rabbitmq:/var/lib/rabbitmq" \
    --entrypoint sh rabbitmq:3.13-management -c \
    "chown -R rabbitmq:rabbitmq /var/lib/rabbitmq && exec docker-entrypoint.sh rabbitmq-server"
fi
for _ in $(seq 1 30); do
  sudo docker exec "$RABBIT_CONTAINER" rabbitmq-diagnostics -q ping >/dev/null 2>&1 && break
  sleep 2
done

sudo git --git-dir=/opt/factortester/repo.git worktree add --detach "$RELEASE_HOST" "$RELEASE_SHA" >/dev/null 2>&1 || true
sudo docker exec "$APP_CONTAINER" mkdir -p /state/job-dispatch-test
sudo docker cp scripts/test/fake_executor.py "$APP_CONTAINER:/tmp/fake_executor.py"
sudo docker exec -u factortester -e PYTHONPATH="$RELEASE_CONTAINER" -w "$RELEASE_CONTAINER" "$APP_CONTAINER" \
  python -c "from server.jobs.repository.sqlite import JobRepository; r=JobRepository('$DB'); r.ensure_schema(); [r.heartbeat_worker_target('$DEPLOYMENT', int(p), f'worker-{p}', ttl_seconds=300) for p in '$PORTS'.split()]"

for port in $PORTS; do
  sudo docker exec -d -u factortester \
    -e PYTHONPATH="$RELEASE_CONTAINER:/tmp" \
    -e FACTORTESTER_BROKER_URL="$BROKER" \
    -e FACTORTESTER_JOB_QUEUE=factortester.jobs \
    -e FACTORTESTER_JOB_DB="$DB" \
    -e FACTORTESTER_DEPLOYMENT_ID="$DEPLOYMENT" \
    -e FACTORTESTER_SERVICE_PORT="$port" \
    -e FACTORTESTER_NAUTILUS_EXECUTOR=fake_executor:executor \
    -w "$RELEASE_CONTAINER" "$APP_CONTAINER" sh -lc \
    "celery -A server.jobs.dispatch.worker_app:app worker --hostname test-$port@%h --pool=solo --concurrency=1 --prefetch-multiplier=1 --loglevel=INFO > /tmp/public-test-$port.log 2>&1"
done
sleep 3
sudo docker exec -u factortester -e PYTHONPATH="$RELEASE_CONTAINER" -w "$RELEASE_CONTAINER" "$APP_CONTAINER" \
  python scripts/test/job_dispatch_smoke.py --db "$DB" --broker "$BROKER" \
  --deployment "$DEPLOYMENT" $(for p in $PORTS; do printf -- '--port %s ' "$p"; done) --timeout 60
