"""Apply effective-dated Instrument updates through NautilusTrader's explicit API.

Call this at an event boundary, after all events before ``effective_ns`` have
been processed and before later data is added. The matching engine is reused;
NautilusTrader updates its instrument state, cancels resting orders which are
incompatible with changed precision, and recalculates account margin for open
exposure. Fee schedules are independent and must use the fill-time clock.
"""

from __future__ import annotations


class UnsafeRuleTransition(RuntimeError):
    """A historical rule change cannot be applied without corrupting state."""


def apply_instrument_rule_transition(
    engine: object,
    instrument: object,
    *,
    effective_ns: int,
    processed_through_ns: int,
    next_event_ns: int,
) -> None:
    """Update an Instrument at a caller-asserted event boundary.

    The caller must run and clear the preceding data chunk before this call,
    then feed only events at or after ``next_event_ns``.  The two timestamps
    make that sequencing reviewable; this function cannot inspect NT's queued
    data or recover matcher state from a replacement.  The data-chunk runner
    must enforce this sequence before using this adapter for a real Job.
    """
    if not isinstance(effective_ns, int) or effective_ns <= 0:
        raise UnsafeRuleTransition("effective_ns must be a positive nanosecond timestamp")
    if not isinstance(processed_through_ns, int) or not isinstance(next_event_ns, int):
        raise UnsafeRuleTransition("event boundary timestamps must be integers")
    if not processed_through_ns < effective_ns <= next_event_ns:
        raise UnsafeRuleTransition("rule transition is not between processed and next events")

    instrument_id = instrument.id
    current = engine.cache.instrument(instrument_id)
    if current is None:
        raise UnsafeRuleTransition(f"{instrument_id}: existing Instrument is absent")
    if current.multiplier != instrument.multiplier:
        raise UnsafeRuleTransition(
            f"{instrument_id}: contract multiplier changed; one Instrument identity "
            "cannot change its notional scale during a run"
        )

    # Emulated and inflight orders have not necessarily entered the matching
    # engine, so its native precision checks cannot safely reconcile them.
    # Resting orders are handled by NautilusTrader's matching-engine update:
    # compatible orders remain; incompatible ones are canceled.
    for kind in ("orders_emulated", "orders_inflight"):
        orders = getattr(engine.cache, kind)(instrument_id=instrument_id)
        if orders:
            raise UnsafeRuleTransition(
                f"{instrument_id}: {len(orders)} {kind} block historical rule transition"
            )
    engine.update_instrument(instrument, effective_ns)
