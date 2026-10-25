# Keycloak cutover runbook

## Preflight

```bash
python scripts/migrations/keycloak_accounts.py \
  --db /data/sqlite/unifieddata.sqlite --output /tmp/accounts.json
```

Check:

```text
case_collisions == {}
```

If not empty, resolve manually before import.

## Import

```bash
export TRADERESEARCH_KEYCLOAK_URL=http://keycloak:8080
export TRADERESEARCH_KEYCLOAK_REALM=trade
export TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_ID=tr-admin
export TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET=...

python scripts/migrations/keycloak_import_accounts.py --input /tmp/accounts.json
python scripts/migrations/keycloak_backfill_legacy.py --input /tmp/accounts.json
python scripts/migrations/keycloak_dual_read.py --input /tmp/accounts.json
python scripts/migrations/keycloak_roles.py \
  --input /tmp/accounts.json --permissions-db /data/sqlite/permissions.db
```

Required realm setting:

```text
unmanagedAttributePolicy = ENABLED
```

Otherwise `legacy_username` is dropped and old usernames cannot be restored.

## Permission entries

Legacy `super_admin`/`operator` are projected to:

```text
admin_console:dispatch read/manage
```

Other report/factor/strategy permissions are not inferred automatically.

## Staged login

```text
TRADERESEARCH_AUTH_MODE=dual
```

Both password and Keycloak work.

Then:

```text
TRADERESEARCH_AUTH_MODE=keycloak
```

Password login returns `403 keycloak_login_required`.

## Rollback

```text
TRADERESEARCH_AUTH_MODE=legacy
```

Keycloak OIDC start/callback return 503; old password login works.

## Verification

```bash
python scripts/test/keycloak_oidc_smoke.py ...
python scripts/test/factortester_oidc_e2e.py \
  --base-url http://127.0.0.1:8000 --username alice --password ...
```

For a migrated legacy user, `/whoami` must return the original case-sensitive
username, not the lowercased Keycloak username.

## Known failure

```text
Keycloak username: gtht@testa@...
whoami username:   gtht@testa@...   (wrong)
```

Cause: callback used the public web client for Admin API. Set:

```text
TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_ID
TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET
```

The admin client must be able to read users.
