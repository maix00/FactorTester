// Copyright 2026 MSD-RS Project LiJia
// SPDX-License-Identifier: BSD-2-Clause
//
// The single interval type consumed by the Rust kernel.  Boundary resolution
// (bars, sessions, wall-clock, event occurrence, truncation) happens in
// TradeResearch and is handed to the kernel as an inclusive ordinal interval.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct IntervalSpec {
  pub start: u64,
  pub end: u64,
}

impl IntervalSpec {
  pub fn new(start: u64, end: u64) -> Result<Self, crate::algo::Error> {
    if end < start {
      return Err(crate::algo::Error::InvalidParameter(
        "interval end must not precede start".to_string(),
      ));
    }
    Ok(Self { start, end })
  }

  pub fn width(self) -> u64 {
    self.end - self.start + 1
  }
}

#[cfg(test)]
mod tests {
  use super::*;

  #[test]
  fn interval_is_inclusive() {
    let interval = IntervalSpec::new(10, 19).unwrap();
    assert_eq!(interval.width(), 10);
  }

  #[test]
  fn invalid_interval_is_rejected() {
    assert!(IntervalSpec::new(5, 4).is_err());
  }
}
