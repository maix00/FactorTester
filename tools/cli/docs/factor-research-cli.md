# FactorTester CLI Research Jobs

The CLI is a remote HTTP client. Research execution has one lifecycle:

1. Create or select a durable research `workspace`.
2. Write the complete open-ended ResearchConfiguration into the workspace. Registry-defined shared and per-analysis settings are preserved without a field whitelist.
3. Submit an immutable `run`; each requested analysis becomes a `job` under that run.
4. Observe, cancel, retry, continue, and query results by `job_id`.

Inside a page-bound Profile Agent runtime, inspect and atomically fill the
currently assisted page with one registered structured document:

```bash
factortester assist inspect
factortester assist drafts create --file assistance.json
factortester assist drafts validate <draft-id>
factortester assist drafts apply <draft-id>
# create also accepts --stdin; the Manager retains the resulting draft.
```

The page publishes the schema and current document. Test pages expose the same
`configuration` shape later frozen as `RunSpec.configuration`; factor and
custom-analysis pages expose their own registered draft schemas. Apply is
all-or-nothing and fails if the person edited the page after inspection.

```bash
factortester workspace create \
  --factor-family SgCCS \
  --factor-family MmRet \
  --factor 'SgCCS=SgCCS|P:CA|N:10d'
factortester workspace templates
factortester workspace load-template <configuration_id>
# Or replace the active configuration from a complete JSON object:
factortester workspace update --file research-configuration.json

# Inspect policy roles, then configure one strategy atomically.
factortester strategy intent describe
factortester strategy intent show --group A1 --json
factortester strategy intent configure A1 \
  --role screen=LiquidityGate --screen-rule gte --screen-lower 1 \
  --role sizing=InverseRisk --allocation-policy factor_sizing \
  --sizing-transform inverse --json

# Public strategy entry: templates and custom Strategy Actor specs.
# StrategyPlan is produced internally after validation; it is not a user-written template.
factortester strategy list --json
factortester strategy template show group_quantile --json
factortester strategy validate --spec strategy.yaml --json

# 持久策略库：策略带不可变源码版本，可按权限共享。
factortester strategy-library list --scope mine --json
factortester strategy-library show strategy:<owner>/<name> --json
factortester strategy-library revisions list strategy:<owner>/<name> --json
factortester strategy-library revisions show strategy:<owner>/<name> <revision-ref> --json

# 当前测试配置中的临时策略：只随 ResearchConfiguration 保存，绝不写入策略库。
factortester workspace strategy list
factortester workspace strategy add-inline \
  --name "盘中反转" --source-file strategy.py \
  --entrypoint IntradayReversal --target-strategy-id group-1
factortester workspace strategy update-inline <binding-id> \
  --source-file strategy-v2.py
factortester workspace strategy bind-library \
  --strategy-ref strategy:<owner>/<name> \
  --revision-ref <revision-ref> --target-strategy-id group-2
factortester workspace strategy show <binding-id> --json
factortester workspace strategy unbind <binding-id>

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
factortester job orders <job_id>
factortester job order <job_id> <order_group_id>
factortester job status <job_id>
factortester job config <job_id>
factortester job progress <job_id>
factortester job output-capabilities --json
factortester job artifacts <job_id> --json
factortester job artifact <job_id> <name>
factortester job download-all <job_id>
factortester job generate <job_id> --output fee_detail --output margin_detail
factortester job cancel <job_id>
factortester job retry <job_id>
factortester job continue <job_id> --end
```

For IC jobs, forward horizons and diagnostic fields are configurable in the
active workspace.  Horizons default to the scale-aware grid; the metric
projection defaults to all fields.  To retain only selected diagnostic groups
or fields in subsequent results, use for example:

```bash
factortester workspace ic-horizons --sampling scale_aware
factortester workspace ic-metrics \
  --metric core --metric holding_half_life --exclude persistence
```

The normalized `ic_metric_selection` is stored in the result and report
artifacts.  Selecting a holding-period half-life implicitly retains
`mean_ic`, its fit dependency, and records that dependency in the metadata.
Use `factortester workspace ic-metrics --all` to restore the complete default.

Saved templates use the same open ResearchConfiguration schema as a workspace. Loading one updates the active configuration and restores the Web registry snapshot; a submitted RunSpec freezes the selected configuration revision and provenance.

`screen` is evaluated at every signal timestamp and changes the eligible
universe before ranking. `sizing` changes only weights inside the selected set.
The command rejects incompatible roles and role bindings that would otherwise
be ignored. A role alias may be deferred when it comes from a Profile
factor-worktree; `run preview` or `run submit` must then include
`--profile-factor-worktree` so the server can validate and freeze its private
source hash for that Run. The deferred alias is never added to the shared
factor library. Use `--clear-role ROLE` to return a role to the primary-factor
fallback.

CLI jobs use the `durable` lifecycle and do not depend on `page_uuid` or a browser view lease. Web observer-bound jobs may be cancelled after their view lease expires; refresh can reclaim the same view UUID during its grace period.

`job orders` reads the retained `order_audit` artifact and prints compact
OrderGroup status, requested quantity, cumulative fills, and active leaves.
`job order` expands atomic Orders, attempts, Fills, settlements, and actions;
use `--order-id` to select one atomic Order. Both commands support `--json` and
require the backtest to have been submitted with `--retain-full`.

Every comparison must keep the ranking universe/product mask, signal visibility, forward-return window, next-open execution, fees, capacity, and sample slices aligned. Failed jobs retain their traceback, cancelled jobs retain a reason, and terminal records remain queryable until the configured TTL.

## Declare and retrieve Job outputs

The server is the authority for output names, Chinese descriptions, supported
formats, and source prerequisites. CLI and UI use the same HTTP contract:

```bash
factortester job output-capabilities --json
factortester run preview --analysis backtest \
  --output equity_curve --output fee_detail --output margin_detail
factortester run submit --analysis backtest --retain-full \
  --output returns_over_time --output metrics_over_time
```

Requested names are frozen into the RunSpec. A detail request retains its
declared source artifacts (`result`, `group_execution`, or `order_audit`) even
when the default raw result would not be retained. After a terminal Job, `job generate` can create
another declared output when its source was retained; otherwise the server
returns the missing prerequisite instead of producing an empty report.
`job artifacts` shows server metadata, `job artifact` downloads one file, and
`job download-all` downloads a ZIP to the current workspace's local Job
directory by default. `job clear-results` deletes server-side files; local
downloads are separate and can be removed by the user or a local workspace
cleanup command.

## Confirm data availability before sample design

The Planning Agent first confirms the product range with the user. It then
requests only that scope; availability must never widen it through an implicit
provider fallback.

```bash
factortester product-library availability \
  --product A.DCE \
  --source Local \
  --frequency MIN1 \
  --json
```

The default command performs a low-cost static inspection. `--probe` explicitly
authorizes a registered connector to perform a network or stream probe. A
provider being installed, reachable, or entitled does not by itself prove
real-time latency or a valid signal-to-execution schedule. `--frequency` is
the actual backing data frequency: a DAY1 signal normally checks MIN1, because
native maps the trading day to its final MIN1 event before scheduling the next
tradable action.

Tiger is a device-local FTClient source for the OSE products `JNI.OSE`,
`JMI.OSE`, `JTM.OSE`, `JTI.OSE`, and `NK225MC.OSE`. FTClient installs its
manifest and connector below `~/Documents/FactorTester/sources/Tiger`; the
server does not register, enumerate, or probe that source, and the local-data
request never leaves the device. Ordinary Web clients therefore cannot select
Tiger. The Swift client exposes the same product and data-source hierarchy
through a bounded internal bridge and stores connector credentials in the
device Keychain. That bridge is not a public factor-library CLI.

The local manifest declares a live OSE order-book stream with L2 market depth.
It does not declare MIN1 or DAY1 bars. Static local-data discovery never imports
or connects the Tiger SDK; a separate explicit local probe is required before
availability or latency may be claimed.

Before freezing a product-by-product TrialPlan, screen liquidity independently
of factor or backtest results. The cutoff is mandatory so the screen cannot
silently inspect a later holdout:

```bash
factortester product-library liquidity \
  --product A.DCE \
  --product RB.SHF \
  --source LocalCNFuturesDAY1 \
  --as-of 2024-12-31 \
  --window-days 365 \
  --json
```

The server projects only the physical DAY1 date and VOLUME columns in one
batch scan, performs no database reads, and returns a hash-bound evidence
document. Each product reports the latest observed daily volume at or before
the cutoff, average daily volume, observed zero-volume days, and exact window
coverage. Missing calendar days are not invented as zero-volume days. Missing
files, columns, or unreadable scans are reported as `capability_gap`; the
command never substitutes turnover, open interest, MIN1 data, or a different
provider. Thresholds remain part of the predeclared TrialPlan rather than this
evidence collector.
