// Copyright 2026 MSD-RS Project LiJia
// SPDX-License-Identifier: BSD-2-Clause
//
// One interval model for windows and scopes.  A scope is not a separate
// kernel: its start is the occurrence of a periodic trading event.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EventKind {
  /// The authoritative start of the current trading day.  Night bars belong
  /// to the following trading day; this is never derived from a calendar date.
  TradingDayStart,
  /// Start of the current continuous trading session (night or day).
  TradingSessionStart,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Boundary {
  Current,
  /// The most recent occurrence of an authoritative trading event.
  LatestEvent(EventKind),
  OffsetFromCurrent(i64),
  /// A bar offset from the most recent event occurrence.
  OffsetFromEvent { event: EventKind, offset: i64 },
  Absolute(u64),
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct IntervalSpec {
  pub start: Boundary,
  pub end: Boundary,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct IntervalContext {
  /// Absolute ordinal of the current bar within the run.
  pub current_index: u64,
  /// Ordinal of the first bar after the latest TradingDayStart event.
  pub trading_day_start_index: u64,
  /// Ordinal of the first bar after the latest TradingSessionStart event.
  pub trading_session_start_index: u64,
}

impl Boundary {
  fn event_index(self, context: IntervalContext) -> Option<u64> {
    match self {
      Boundary::LatestEvent(EventKind::TradingDayStart) => {
        Some(context.trading_day_start_index)
      }
      Boundary::LatestEvent(EventKind::TradingSessionStart) => {
        Some(context.trading_session_start_index)
      }
      _ => None,
    }
  }

  fn resolve(self, context: IntervalContext) -> Option<u64> {
    match self {
      Boundary::Current => Some(context.current_index),
      Boundary::LatestEvent(kind) => Boundary::LatestEvent(kind).event_index(context),
      Boundary::Absolute(value) => Some(value),
      Boundary::OffsetFromCurrent(offset) => Some(offset_index(
        context.current_index,
        offset,
      )),
      Boundary::OffsetFromEvent { event, offset } => {
        let base = Boundary::LatestEvent(event).event_index(context)?;
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
  pub fn resolve(self, context: IntervalContext) -> Option<(u64, u64)> {
    let start = self.start.resolve(context)?;
    let end = self.end.resolve(context)?;
    if end < start {
      None
    } else {
      Some((start, end))
    }
  }

  pub fn contains(self, context: IntervalContext, index: u64) -> bool {
    self.resolve(context)
      .is_some_and(|(start, end)| start <= index && index <= end)
  }
}

#[cfg(test)]
mod tests {
  use super::*;

  fn context() -> IntervalContext {
    IntervalContext {
      current_index: 120,
      trading_day_start_index: 100,
      trading_session_start_index: 110,
    }
  }

  #[test]
  fn trading_day_scope_starts_at_the_trading_day_event() {
    let spec = IntervalSpec {
      start: Boundary::LatestEvent(EventKind::TradingDayStart),
      end: Boundary::Current,
    };
    assert_eq!(spec.resolve(context()), Some((100, 120)));
    assert!(spec.contains(context(), 100));
    assert!(!spec.contains(context(), 99));
  }

  #[test]
  fn session_scope_starts_at_the_session_event() {
    let spec = IntervalSpec {
      start: Boundary::LatestEvent(EventKind::TradingSessionStart),
      end: Boundary::Current,
    };
    assert_eq!(spec.resolve(context()), Some((110, 120)));
  }

  #[test]
  fn truncation_offsets_from_the_event() {
    let spec = IntervalSpec {
      start: Boundary::OffsetFromEvent {
        event: EventKind::TradingDayStart,
        offset: 0,
      },
      end: Boundary::OffsetFromEvent {
        event: EventKind::TradingDayStart,
        offset: 19,
      },
    };
    assert_eq!(spec.resolve(context()), Some((100, 119)));
  }

  #[test]
  fn lookback_window_is_an_interval_from_current() {
    let spec = IntervalSpec {
      start: Boundary::OffsetFromCurrent(-249),
      end: Boundary::Current,
    };
    assert_eq!(spec.resolve(context()), Some((0, 120)));
  }
}
