# FactorTester CLI Research Jobs

The CLI is a remote HTTP client. Research execution has one lifecycle:

1. Create or select a durable research `workspace`.
2. Write the complete open-ended ResearchConfiguration into the workspace. Registry-defined shared and per-analysis settings are preserved without a field whitelist.
3. Submit an immutable `run`; each requested analysis becomes a `job` under that run.
4. Observe, cancel, retry, continue, and query results by `job_id`.

```bash
factortester workspace create \
  --factor-family SgCCS \
  --factor-family MmRet \
  --factor 'SgCCS=SgCCS|P:CA|N:10d'
factortester workspace templates
factortester workspace load-template <configuration_id>
# Or replace the active configuration from a complete JSON object:
factortester workspace update --file research-configuration.json

# Validate the full panel through GTHT and freeze its id/hashes in this workspace:
factortester external-factor validate \
  /path/to/gtht_handoff.json \
  --attach

factortester run submit \
  --analysis ic \
  --analysis factor_evaluation \
  --analysis factor_type_analysis \
  --analysis backtest

factortester job list
factortester job watch <job_id>
factortester job status <job_id>
factortester job artifact <job_id> <name>
factortester job cancel <job_id>
factortester job retry <job_id>
factortester job continue <job_id> --end
```

Saved templates use the same open ResearchConfiguration schema as a workspace. Loading one updates the active configuration and restores the Web registry snapshot; a submitted RunSpec freezes the selected configuration revision and provenance.

CLI jobs use the `durable` lifecycle and do not depend on `page_uuid` or a browser view lease. Web observer-bound jobs may be cancelled after their view lease expires; refresh can reclaim the same view UUID during its grace period.

Every comparison must keep the ranking universe/product mask, signal visibility, forward-return window, next-open execution, fees, capacity, and sample slices aligned. Failed jobs retain their traceback, cancelled jobs retain a reason, and terminal records remain queryable until the configured TTL.

## Confirm data availability before sample design

The Planning Agent first confirms the product range with the user. It then
requests only that scope; availability must never widen it through an implicit
provider fallback.

```bash
factortester products availability \
  --product A.DCE \
  --source Local \
  --json
```

The default command performs a low-cost static inspection. `--probe` explicitly
authorizes a registered connector to perform a network or stream probe. A
provider being installed, reachable, or entitled does not by itself prove
real-time latency or point-in-time coverage.

Tiger is a selectable source for the first-class OSE products `JNI.OSE`,
`JMI.OSE`, `JTM.OSE`, `JTI.OSE`, and `NK225MC.OSE`. Its SDK runtime and
protected properties path are server-side settings; they are never returned
to the CLI.

```bash
factortester products availability \
  --product JNI.OSE \
  --product JMI.OSE \
  --source Tiger \
  --probe \
  --json
```

The response reports the file-backed MIN1/DAY1 cache independently from the
L2 probe. An active `OSEFuturesQuoteLv2` entitlement is reported separately
from `latency_class`; the latter remains `unverified` until a market-session
latency test has been accepted.
