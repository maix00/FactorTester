// Copyright 2026 MSD-RS Project LiJia
// SPDX-License-Identifier: BSD-2-Clause
//
// One interval model for windows and scopes.  A scope is not a separate
// kernel: it is an interval whose start boundary is a partition boundary.

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Boundary {
  Current,
  PartitionStart,
  OffsetFromCurrent(i64),
  OffsetFromPartition(i64),
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
  /// Absolute ordinal of the first bar in the current partition.
  pub partition_start_index: u64,
}

impl Boundary {
  fn resolve(self, context: IntervalContext) -> Option<u64> {
    match self {
      Boundary::Current => Some(context.current_index),
      Boundary::PartitionStart => Some(context.partition_start_index),
      Boundary::Absolute(value) => Some(value),
      Boundary::OffsetFromCurrent(offset) => Some(if offset < 0 {
        context.current_index.saturating_sub(offset.unsigned_abs())
      } else {
        context.current_index.saturating_add(offset as u64)
      }),
      Boundary::OffsetFromPartition(offset) => Some(if offset < 0 {
        context.partition_start_index.saturating_sub(offset.unsigned_abs())
      } else {
        context.partition_start_index.saturating_add(offset as u64)
      }),
    }
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
    IntervalContext { current_index: 120, partition_start_index: 100 }
  }

  #[test]
  fn scope_is_an_interval_with_partition_start() {
    let spec = IntervalSpec {
      start: Boundary::PartitionStart,
      end: Boundary::Current,
    };
    assert_eq!(spec.resolve(context()), Some((100, 120)));
    assert!(spec.contains(context(), 100));
    assert!(!spec.contains(context(), 99));
  }

  #[test]
  fn truncation_moves_both_boundaries() {
    let spec = IntervalSpec {
      start: Boundary::OffsetFromPartition(0),
      end: Boundary::OffsetFromPartition(119),
    };
    assert_eq!(spec.resolve(context()), Some((100, 219)));
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
