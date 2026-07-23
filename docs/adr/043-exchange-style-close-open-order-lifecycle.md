# ADR-043: Exchange-style close/open order lifecycle

- **Date**: 2026-07-23
- **Status**: Proposed
- **GitHub issue**: Not registered
- **Related**: ADR-027, ADR-031, ADR-034, ADR-041, ADR-042

## Context

The native engine can account for a net reversal atomically. For example, an
order delta of `-15` against a current long position of `10` produces a final
short position of `5`; fee and ledger helpers infer the close and open portions
to calculate realized P&L, fees, and final margin.

This is a full-fill accounting approximation, not an exchange-style order
lifecycle. `Order` has no first-class open/close, close-today/close-yesterday,
parent group, dependency, filled quantity, remaining quantity, or partial-fill
state. Liquidity excess is capped rather than carried as a live remainder.

Domestic futures gateways require an offset flag. A reversal is therefore at
least a close order plus an open order, and may split the close again by
close-today and close-yesterday. Their fills can occur at different times and
prices. Margin released by an unfilled close order must not fund a new open
order.

As of the date above, this capability gap has **not** been registered as a
GitHub issue. This ADR records a proposed design and acceptance boundary; it
does not add the work to Issue #143.

## Decision

Keep the existing atomic net-delta path as an explicitly named approximation.
Do not describe it as exchange-exact execution.

Add an exchange-style path in a future issue:

1. Decompose a target delta against closeable lots into explicit
   `close_today`, `close_yesterday`, and `open` order legs.
2. Link those legs with one `order_group_id` and `parent_intent_id`.
3. Allow the open leg to declare a dependency on actual close fills.
4. Track `filled_quantity`, `remaining_quantity`, fill records, and a
   `partially_filled` state.
5. Recompute positions, realized P&L, fees, cash, and portfolio margin after
   every fill; never reserve or release margin from an assumed fill.
6. Apply liquidity and hard margin limits only to the margin-increasing
   remainder. Position-reducing legs remain executable.
7. Keep live pending legs indexed individually. Cancellation, replacement, and
   rescheduling operate on legs and preserve the parent order-group audit.

Sequential close-then-open is the default when the open leg depends on released
margin. Parallel submission is a separate execution policy and must prove that
the account has enough buying power if the open leg fills first.

Exchange and broker rules remain data-driven. Offset flags, close-today fees,
position-lot selection, margin offsets, and combination benefits must not be
invented by the generic order model.

## Observability

Order-flow and step output must show:

- parent intent and order-group identities;
- leg role and offset flag;
- requested, filled, and remaining quantities;
- activation dependency and activation reason;
- per-fill price, fee, realized P&L, margin before/after, and cash before/after;
- cancellation, rejection, and unfilled-remainder reasons.

The default view stays compact at order-group level. CLI detail output may
expand legs and fills without truncation.

## Acceptance

- Reversing long `10` to short `5` produces close legs totaling `10` and an
  open leg of `5`; no single exchange order mixes close and open quantities.
- When the close fills only `6`, only the corresponding margin is released and
  the dependent open leg is activated or resized from that actual state.
- Close-today and close-yesterday quantities follow the configured lot policy
  and receive their own fees and offset flags.
- A hard margin-utilization cap never reduces a risk-releasing close leg. It
  constrains only the margin-increasing open remainder.
- If open fills before close under an explicitly parallel policy, the
  intermediate locked position and its actual margin requirement are recorded.
- Pending indexes, event queue, order statuses, and fill records contain the
  same live leg set after partial fill, cancellation, replacement, and retry.
- Bar-volume capacity carries an unfilled remainder when the execution policy
  permits it; it does not silently discard the excess.
- Atomic approximation and exchange-style execution produce the same final
  ledger result when all legs fill completely at one price with no
  intermediate constraint.
- Exact mode refuses to run exchange-style execution when required offset,
  lot-age, fee, margin, or fill data is unavailable.

## References

- China Financial Futures Exchange trader API, `CombOffsetFlag`
- Shanghai Futures Exchange trading API and market-data interface specification
- ADR-042 margin-budget and buying-power decisions
