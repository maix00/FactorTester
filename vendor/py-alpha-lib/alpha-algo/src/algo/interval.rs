// Copyright 2026 MSD-RS Project LiJia
// SPDX-License-Identifier: BSD-2-Clause
//
// One interval model for windows and scopes.  A scope is not a separate
// kernel: its start is the latest occurrence of an authoritative event.
// Events may be periodic (trading day/session) or irregular but recurring
// (contract roll, halt/resume, settlement, instrument change, ...).

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct EventId(pub usize);

pub const TRADING_DAY_START: EventId = EventId(0);
pub const TRADING_SESSION_START: EventId = EventId(1);

/// Latest observed occurrence of every event, as an absolute bar ordinal.
/// The event source (trading calendar, roll schedule, halt feed, ...) is owned
/// by TradeResearch; this type only consumes resolved occurrences.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct EventTimeline {
  latest: Vec<Option<u64>>,
}

impl EventTimeline {
  pub fn new(event_count: usize) -> Self {
    Self { latest: vec![None; event_count] }
  }

  pub fn set(&mut self, event: EventId, occurrence: u64) {
    if self.latest.len() <= event.0 {
      self.latest.resize(event.0 + 1, None);
    }
    self.latest[event.0] = Some(occurrence);
  }

  pub fn latest(&self, event: EventId) -> Option<u64> {
    self.latest.get(event.0).copied().flatten()
  }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Boundary {
  Current,
  /// Latest occurrence of an event, periodic or not.
  LatestEvent(EventId),
  OffsetFromCurrent(i64),
  /// A bar offset from the latest occurrence of an event.
  OffsetFromEvent { event: EventId, offset: i64 },
  Absolute(u64),
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct IntervalSpec {
  pub start: Boundary,
  pub end: Boundary,
}

#[derive(Clone, Copy, Debug)]
pub struct IntervalContext<'a> {
  /// Absolute ordinal of the current bar within the run.
  pub current_index: u64,
  pub events: &'a EventTimeline,
}

impl Boundary {
  fn resolve(self, context: &IntervalContext<'_>) -> Option<u64> {
    match self {
      Boundary::Current => Some(context.current_index),
      Boundary::LatestEvent(event) => context.events.latest(event),
      Boundary::Absolute(value) => Some(value),
      Boundary::OffsetFromCurrent(offset) => Some(offset_index(
        context.current_index,
        offset,
      )),
      Boundary::OffsetFromEvent { event, offset } => {
        let base = context.events.latest(event)?;
        Some(offset_index(base, offset))
      }
    }
  }
}

fn offset_index(base: u64, offset: i64) -> u64 {
  if offset < 0 {
    base.saturating_sub(offset.unsigned_abs())
  } else {
    base.saturating_add(offset as u64)
  }
}

impl IntervalSpec {
  /// Resolve inclusive `[start, end]`.  Returns `None` when the interval is
  /// outside the current run, or when `end` is before `start`.
  pub fn resolve(self, context: &IntervalContext<'_>) -> Option<(u64, u64)> {
    let start = self.start.resolve(context)?;
    let end = self.end.resolve(context)?;
    if end < start {
      None
    } else {
      Some((start, end))
    }
  }

  pub fn contains(self, context: &IntervalContext<'_>, index: u64) -> bool {
    self.resolve(context)
      .is_some_and(|(start, end)| start <= index && index <= end)
  }
}

#[cfg(test)]
mod tests {
  use super::*;

  fn context() -> (EventTimeline, u64) {
    let mut events = EventTimeline::new(2);
    events.set(TRADING_DAY_START, 100);
    events.set(TRADING_SESSION_START, 110);
    (events, 120)
  }

  fn ctx<'a>(events: &'a EventTimeline, current: u64) -> IntervalContext<'a> {
    IntervalContext { current_index: current, events }
  }

  #[test]
  fn trading_day_scope_starts_at_the_trading_day_event() {
    let (events, current) = context();
    let spec = IntervalSpec {
      start: Boundary::LatestEvent(TRADING_DAY_START),
      end: Boundary::Current,
    };
    assert_eq!(spec.resolve(&ctx(&events, current)), Some((100, 120)));
    assert!(spec.contains(&ctx(&events, current), 100));
    assert!(!spec.contains(&ctx(&events, current), 99));
  }

  #[test]
  fn session_scope_starts_at_the_session_event() {
    let (events, current) = context();
    let spec = IntervalSpec {
      start: Boundary::LatestEvent(TRADING_SESSION_START),
      end: Boundary::Current,
    };
    assert_eq!(spec.resolve(&ctx(&events, current)), Some((110, 120)));
  }

  #[test]
  fn non_periodic_event_can_anchor_an_interval() {
    let roll = EventId(2);
    let mut events = EventTimeline::new(3);
    events.set(roll, 115);
    let spec = IntervalSpec {
      start: Boundary::OffsetFromEvent { event: roll, offset: -2 },
      end: Boundary::LatestEvent(roll),
    };
    assert_eq!(spec.resolve(&ctx(&events, 120)), Some((113, 115)));
  }

  #[test]
  fn truncation_offsets_from_the_event() {
    let (events, current) = context();
    let spec = IntervalSpec {
      start: Boundary::OffsetFromEvent { event: TRADING_DAY_START, offset: 0 },
      end: Boundary::OffsetFromEvent { event: TRADING_DAY_START, offset: 19 },
    };
    assert_eq!(spec.resolve(&ctx(&events, current)), Some((100, 119)));
  }

  #[test]
  fn lookback_window_is_an_interval_from_current() {
    let (events, current) = context();
    let spec = IntervalSpec {
      start: Boundary::OffsetFromCurrent(-249),
      end: Boundary::Current,
    };
    assert_eq!(spec.resolve(&ctx(&events, current)), Some((0, 120)));
  }
}
