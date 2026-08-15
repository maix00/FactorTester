# Manager CLI test plan

## Test inventory

- `tests/cli/test_manager_commands.py`: 9 unit/Click command tests for
  authentication, boundary removal, server declarations, Jobs, and service
  actions.
- `tests/cli/test_manager_access.py`: 6 tests for redacted local credential
  checks, script download gating, explicit override, Job confirmation, and
  application-only command exposure.
- `tests/cli/test_manager_cli_subprocess.py`: 3 installed/fallback subprocess
  tests for help and local configuration.
- `tests/server/test_manager_server_access.py`: 8 server-settings projection,
  health, and digest-checked script route tests.

## Unit coverage

The tests cover the URL-scoped Manager credential boundary, the explicit
super-admin capability check, read-only server access projection, local
credential readiness without secret access, digest-checked script transfer,
Job/service command naming, artifact/data-plane command presence, and
rejection of legacy host-admin commands. Invalid, missing, and duplicate
service-port selections are included.

## E2E/subprocess coverage

The subprocess tests resolve `factortester-manager` from `PATH` when available
and fall back to the source module for local development. They do not set a
working directory, and they validate real Click help/configuration behavior
without requiring a live Manager account.

## Test results

Command:

`conda run -n GTHT python -m pytest -q tests/cli/test_manager_access.py tests/cli/test_manager_cli_subprocess.py tests/server/test_manager_server_access.py tests/cli/test_manager_commands.py tests/cli/test_admin_commands.py tests/cli/test_agent_flow_release_surface.py tests/release/test_release_materialization.py`

Result: **30 passed** for the current targeted Manager/CLI/server boundary
suite, including the real HTTP identity, health, and script routes.
