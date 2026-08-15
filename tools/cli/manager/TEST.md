# Manager CLI test plan

## Test inventory

- `tests/cli/test_manager_commands.py`: 9 unit/Click command tests for
  authentication, boundary removal, server declarations, Jobs, and service
  actions.
- `tests/cli/test_manager_cli_subprocess.py`: 3 installed/fallback subprocess
  tests for help and local configuration.
- `tests/server/test_manager_server_access.py`: 4 server-settings projection
  tests.

## Unit coverage

The tests cover the URL-scoped Manager credential boundary, the explicit
super-admin capability check, read-only server access projection, Job/service
command naming, artifact/data-plane command presence, and rejection of legacy
host-admin commands. Invalid, missing, and duplicate service-port selections
are included.

## E2E/subprocess coverage

The subprocess tests resolve `factortester-manager` from `PATH` when available
and fall back to the source module for local development. They do not set a
working directory, and they validate real Click help/configuration behavior
without requiring a live Manager account.

## Test results

Command:

`conda run -n GTHT python -m pytest -q tests/cli/test_manager_cli_subprocess.py tests/server/test_manager_server_access.py tests/cli/test_manager_commands.py tests/cli/test_admin_commands.py tests/cli/test_agent_flow_release_surface.py`

Result: **20 passed** for the complete targeted boundary suite; the focused
Manager/CLI/server subset currently reports **16 passed**.
