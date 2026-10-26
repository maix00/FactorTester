//! CURRENT/CANDIDATE search kernel shared by batch, incremental and bridge.

#[derive(Clone, Debug)]
pub enum MatchExpr {
    Current,
    Candidate,
    Const(f64),
    Add(Box<MatchExpr>, Box<MatchExpr>),
    Sub(Box<MatchExpr>, Box<MatchExpr>),
    Mul(Box<MatchExpr>, Box<MatchExpr>),
    Div(Box<MatchExpr>, Box<MatchExpr>),
    Abs(Box<MatchExpr>),
    Gt(Box<MatchExpr>, Box<MatchExpr>),
    Lt(Box<MatchExpr>, Box<MatchExpr>),
    Ge(Box<MatchExpr>, Box<MatchExpr>),
    Le(Box<MatchExpr>, Box<MatchExpr>),
    Eq(Box<MatchExpr>, Box<MatchExpr>),
    Ne(Box<MatchExpr>, Box<MatchExpr>),
}

impl MatchExpr {
    pub fn eval(&self, current: f64, candidate: f64) -> f64 {
        match self {
            Self::Current => current,
            Self::Candidate => candidate,
            Self::Const(value) => *value,
            Self::Add(a, b) => a.eval(current, candidate) + b.eval(current, candidate),
            Self::Sub(a, b) => a.eval(current, candidate) - b.eval(current, candidate),
            Self::Mul(a, b) => a.eval(current, candidate) * b.eval(current, candidate),
            Self::Div(a, b) => a.eval(current, candidate) / b.eval(current, candidate),
            Self::Abs(a) => a.eval(current, candidate).abs(),
            Self::Gt(a, b) => f64::from(a.eval(current, candidate) > b.eval(current, candidate)),
            Self::Lt(a, b) => f64::from(a.eval(current, candidate) < b.eval(current, candidate)),
            Self::Ge(a, b) => f64::from(a.eval(current, candidate) >= b.eval(current, candidate)),
            Self::Le(a, b) => f64::from(a.eval(current, candidate) <= b.eval(current, candidate)),
            Self::Eq(a, b) => f64::from(a.eval(current, candidate) == b.eval(current, candidate)),
            Self::Ne(a, b) => f64::from(a.eval(current, candidate) != b.eval(current, candidate)),
        }
    }
}

/// Search ``candidates`` for the nearest/farthest predicate match.
///
/// ``candidates`` are (ordinal, value) pairs with ordinal < current_ordinal.
/// Only candidates inside ``[current_ordinal - scope, current_ordinal)`` count.
pub fn match_distance(
    current_ordinal: u64,
    current: f64,
    candidates: &[(u64, f64)],
    predicate: &MatchExpr,
    scope: u64,
    nearest: bool,
    default: f64,
) -> f64 {
    match_distance_iter(current_ordinal, current, candidates.iter().copied(), predicate, scope, nearest, default)
}

pub fn match_distance_iter<I>(
    current_ordinal: u64,
    current: f64,
    candidates: I,
    predicate: &MatchExpr,
    scope: u64,
    nearest: bool,
    default: f64,
) -> f64
where
    I: IntoIterator<Item = (u64, f64)>,
{
    let start = current_ordinal.saturating_sub(scope);
    let mut matched: Option<u64> = None;
    for (ordinal, value) in candidates {
        if ordinal < start || ordinal >= current_ordinal { continue; }
        if predicate.eval(current, value) != 0.0 {
            matched = Some(match matched {
                None => ordinal,
                Some(previous) if nearest => previous.max(ordinal),
                Some(previous) => previous.min(ordinal),
            });
        }
    }
    matched.map_or(default, |ordinal| (current_ordinal - ordinal) as f64)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn current_candidate_references_evaluate_in_rust() {
        let predicate = MatchExpr::Ge(
            Box::new(MatchExpr::Sub(Box::new(MatchExpr::Current), Box::new(MatchExpr::Candidate))),
            Box::new(MatchExpr::Const(1.5)),
        );
        let candidates = [(0, 8.0), (1, 8.0), (2, 9.5)];
        assert_eq!(match_distance(3, 10.0, &candidates, &predicate, 3, true, 9.0), 2.0);
        assert_eq!(match_distance(3, 10.0, &candidates, &predicate, 3, false, 9.0), 3.0);
    }
}
