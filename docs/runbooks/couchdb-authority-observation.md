# CouchDB authority observation window

Started: 2026-10-25T19:50:00+08:00 (public revision `ae67b22`).

During the window:

- Keep the legacy SQLite/JSON/mirror data as rollback material.
- Do not delete `/data/sqlite`, publications, mirrors, or local object files.
- Check the public app daily:

```bash
ssh launch-advisor
sudo docker exec factortester-public-factortester-public-1 \
  sh -c 'env | grep FACTORTESTER_COUCHDB'
```

- Verify read paths: product groups, factors, strategies, Research Reports.
- Verify write paths on a disposable test group/factor, then remove it.
- Watch CouchDB conflicts and app logs for fallback warnings.

Exit criteria (not before 2026-11-01):

1. No authority read/write fallback errors for 7 days.
2. A CouchDB backup exists separately from the legacy data.
3. Rollback to `ae67b22` and back to the current revision has been tested.
4. Only then remove legacy SQLite/JSON/mirror files.

Rollback while the window is open:

```bash
# stop the app only, restore the prior public.env, start it again
```
