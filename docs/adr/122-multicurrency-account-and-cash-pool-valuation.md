# ADR 122: Multi-currency accounts and cash-pool valuation

Status: Accepted

## Context

A cash pool used to store one `DataMoney` object and every ledger in that pool
read and replaced that object. This made an account currency indistinguishable
from the pool's base currency and made a mixed-currency pool impossible.

Broker account models distinguish currency-specific cash balances from the
base-currency account summary. A shared buying-power boundary must retain both
facts and value each account at the causal timestamp.

## Decision

- `LedgerConfig.account_currency` is the registered currency of one account.
  `CashPoolConfig.base_currency` remains the pool's common valuation currency.
- `CashPoolStore` owns one immutable `DataMoney` balance per ledger. Different
  ledgers never share a balance object, even when they share a pool.
- Initial pool capital is recorded once. It is assigned to a base-currency
  account when one exists; otherwise it remains an unallocated base-currency
  pool reserve.
- Pool cash, equity, margin and utilization convert every account component to
  the pool base currency using the FX observation at the event timestamp.
- FX observations are cached by pool, currency pair, timestamp and provider so
  all consumers in one causal event use the same rate without repeated reads.
- A missing or non-positive cross-currency rate is an error. It is never
  replaced with one or with a current non-causal rate.
- Passive valuation does not charge a hypothetical conversion fee. Buying
  power and execution projections value positive foreign cash net of the
  registered conversion fee and foreign cash requirements inclusive of that
  fee. An actual future FX transfer must book its fee as a settlement event.
- Fill, settlement and audit projections retain account ID, pool ID, account
  currency and pool base currency as separate fields.

`LedgerState.base_currency` remains the internal name of the account-currency
slot for now; new configuration and result contracts use `account_currency`.
It must never be populated from a pool base currency when an explicit account
currency exists.

## Consequences

Same-currency private pools retain their prior arithmetic. Shared pools no
longer duplicate initial capital and no longer depend on whichever account is
visited first. Mixed-currency runs require a historical FX provider for every
observed pair and timestamp. Cash constraints, margin budgets, equity curves
and margin-risk checks share the same pool valuation boundary.

## References

- https://www.interactivebrokers.com/docs/web-api/v1/endpoints/portfolio/portfolio-summary
- https://interactivebrokers.github.io/tws-api/account_summary.html

