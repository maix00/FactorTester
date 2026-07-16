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
