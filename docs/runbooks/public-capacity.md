# Public capacity and cleanup

## Check

```bash
scripts/server/check_public_capacity.sh
```

Thresholds (overridable):

- root free >= 10G
- `/data` free >= 10G
- MemAvailable >= 1024MB

## Layout

- Manager state: `/data/state` (`FACTORTESTER_STATE_ROOT`)
- Docker: `/var/lib/docker` on the root volume
- Backups: `/opt/factortester-container/backups`

## Incident response

1. Run the capacity check.
2. Inspect `docker system df`, `du -xh -d2 /data /opt /var`.
3. Remove only unused artifacts: `docker builder prune -af`, `docker image prune -af`.
4. Do not prune stopped business containers; PostgreSQL may be stopped during reboot.
5. Do not delete `job-index.sqlite` while the app is running.
6. Use `scripts/server/prune_control_events.py --older-than-days N` without
   `--apply` first; apply only after checking `control_sync_cursors`.
7. Build only when `check_public_build_capacity.sh` passes.

## State rollback

1. Stop the app only.
2. Set `FACTORTESTER_STATE_ROOT` back to the previous path.
3. Start the app and verify `/state/job-index.sqlite` and health.


## Installed monitor

`factortester-capacity-check.timer` runs every 15 minutes and writes
`/data/state/CAPACITY_ALERT` on failure (removed on recovery). Check:

```bash
systemctl list-timers factortester-capacity-check.timer
sudo journalctl -u factortester-capacity-check.service -n 5
cat /data/state/CAPACITY_ALERT
```


## Control-event retention

Installed `factortester-control-events-retention.timer` (daily 03:30). It runs:

```text
factortester-prune-control-events /data/state/job-index.sqlite   --older-than-days 90 --apply --vacuum
```

The tool refuses to delete when `control_sync_cursors` is behind. It
currently reports `candidates=0` because all events are younger than 90 days.
