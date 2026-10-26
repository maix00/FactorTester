//! A small stateful FactorExpr DAG evaluated entirely in Rust.
//!
//! The Python public API will serialize into this spec; the bridge consumes it
//! one `MarketBar` at a time.  No pandas/Python objects are involved.

use std::collections::VecDeque;

use alpha_algo::{IntervalKernel, SessionOp};

use crate::{FactorEngine, MarketBar};

#[derive(Clone, Copy, Debug)]
pub enum BinaryOp { Add, Sub, Mul, Div, Gt, Lt, Ge, Le, Eq, Ne }

#[derive(Clone, Copy, Debug)]
pub enum CrossOp { ZScore, Rank }

#[derive(Clone, Debug)]
pub enum ExprSpec {
    Column(usize),
    Const(f64),
    Rolling { child: usize, window: usize, op: SessionOp, min_periods: usize, propagate_nan: bool },
    Binary { op: BinaryOp, left: usize, right: usize },
    Shift { child: usize, periods: usize },
    Where { condition: usize, when_true: usize, when_false: usize },
    Cross { op: CrossOp, child: usize },
    Since { condition: usize, count: usize, include_current: bool, nearest: bool, default_scope: bool, default: f64 },
}

struct NodeState {
    spec: ExprSpec,
    rolling: Vec<Option<IntervalKernel>>,
    history: VecDeque<Vec<f64>>,
}

pub struct FactorPlanEngine {
    products: usize,
    nodes: Vec<NodeState>,
    outputs: Vec<usize>,
    ordinal: u64,
    since_first: Vec<Option<usize>>,
    since_last: Vec<Option<usize>>,
    since_base: Vec<usize>,
}

fn binary(op: BinaryOp, left: f64, right: f64) -> f64 {
    match op {
        BinaryOp::Add => left + right, BinaryOp::Sub => left - right,
        BinaryOp::Mul => left * right, BinaryOp::Div => left / right,
        BinaryOp::Gt => f64::from(left > right), BinaryOp::Lt => f64::from(left < right),
        BinaryOp::Ge => f64::from(left >= right), BinaryOp::Le => f64::from(left <= right),
        BinaryOp::Eq => f64::from(left == right), BinaryOp::Ne => f64::from(left != right),
    }
}

impl FactorPlanEngine {
    pub fn new(products: usize, specs: Vec<ExprSpec>, outputs: Vec<usize>) -> Result<Self, alpha_algo::Error> {
        if products == 0 || specs.is_empty() || outputs.is_empty() {
            return Err(alpha_algo::Error::InvalidParameter("plan requires products, nodes and outputs".into()));
        }
        let mut nodes = Vec::with_capacity(specs.len());
        for spec in specs {
            let rolling = match &spec {
                ExprSpec::Rolling { op, .. } => (0..products)
                    .map(|_| IntervalKernel::new_explicit(*op).map(Some))
                    .collect::<Result<Vec<_>, _>>()?,
                _ => (0..products).map(|_| None).collect(),
            };
            nodes.push(NodeState { spec, rolling, history: VecDeque::new() });
        }
        if outputs.iter().any(|index| *index >= nodes.len()) {
            return Err(alpha_algo::Error::InvalidParameter("plan output out of range".into()));
        }
        Ok(Self {
            products, nodes, outputs, ordinal: 0,
            since_first: vec![None; products],
            since_last: vec![None; products],
            since_base: vec![0; products],
        })
    }

    fn eval(&mut self, index: usize, columns: &[f64], cache: &mut [Option<Vec<f64>>]) -> Result<Vec<f64>, alpha_algo::Error> {
        if let Some(value) = &cache[index] { return Ok(value.clone()); }
        let spec = self.nodes[index].spec.clone();
        let value = match spec {
            ExprSpec::Column(column) => {
                if column >= columns.len() { return Err(alpha_algo::Error::InvalidParameter("column out of range".into())); }
                vec![columns[column]; self.products]
            }
            ExprSpec::Const(value) => vec![value; self.products],
            ExprSpec::Rolling { child, window, min_periods, propagate_nan, .. } => {
                let input = self.eval(child, columns, cache)?;
                let current = self.ordinal;
                let start = current.saturating_sub(window as u64 - 1);
                let node = &mut self.nodes[index];
                input.iter().enumerate().map(|(product, value)| {
                    let Some(state) = node.rolling[product].as_mut() else { return f64::NAN };
                    state.set_semantics(min_periods, propagate_nan);
                    state.update_explicit(start, current, *value)
                }).collect()
            }
            ExprSpec::Binary { op, left, right } => {
                let a = self.eval(left, columns, cache)?;
                let b = self.eval(right, columns, cache)?;
                a.iter().zip(&b).map(|(x, y)| binary(op, *x, *y)).collect()
            }
            ExprSpec::Shift { child, periods } => {
                let input = self.eval(child, columns, cache)?;
                let history = &mut self.nodes[index].history;
                history.push_back(input);
                while history.len() > periods + 1 { history.pop_front(); }
                if history.len() <= periods { vec![f64::NAN; self.products] }
                else { history[history.len() - 1 - periods].clone() }
            }
            ExprSpec::Where { condition, when_true, when_false } => {
                let condition = self.eval(condition, columns, cache)?;
                let when_true = self.eval(when_true, columns, cache)?;
                let when_false = self.eval(when_false, columns, cache)?;
                condition.iter().zip(when_true.iter().zip(&when_false))
                    .map(|(c, (a, b))| if c.is_finite() && *c != 0.0 { *a } else { *b }).collect()
            }
            ExprSpec::Since { condition, count, include_current, nearest, default_scope, default } => {
                let condition = self.eval(condition, columns, cache)?;
                let mut out = vec![f64::NAN; self.products];
                for product in 0..self.products {
                    if self.ordinal as usize % count == 0 {
                        self.since_base[product] = self.ordinal as usize;
                        self.since_first[product] = None;
                        self.since_last[product] = None;
                    }
                    let truth = condition[product].is_finite() && condition[product] != 0.0;
                    if truth && include_current {
                        if self.since_first[product].is_none() { self.since_first[product] = Some(self.ordinal as usize); }
                        self.since_last[product] = Some(self.ordinal as usize);
                    }
                    let matched = if nearest { self.since_last[product] } else { self.since_first[product] };
                    out[product] = match matched {
                        Some(hit) => (self.ordinal as usize - hit) as f64,
                        None => if default_scope { (self.ordinal as usize - self.since_base[product]) as f64 } else { default },
                    };
                    if truth && !include_current {
                        if self.since_first[product].is_none() { self.since_first[product] = Some(self.ordinal as usize); }
                        self.since_last[product] = Some(self.ordinal as usize);
                    }
                }
                out
            }
            ExprSpec::Cross { op, child } => {
                let input = self.eval(child, columns, cache)?;
                match op {
                    CrossOp::ZScore => {
                        let valid: Vec<f64> = input.iter().copied().filter(|v| v.is_finite()).collect();
                        let n = valid.len() as f64;
                        let mean = valid.iter().sum::<f64>() / n;
                        let std = (valid.iter().map(|v| (v - mean).powi(2)).sum::<f64>() / (n - 1.0).max(1.0)).sqrt();
                        input.iter().map(|v| if !v.is_finite() { f64::NAN } else if std == 0.0 { 0.0 } else { (v - mean) / std }).collect()
                    }
                    CrossOp::Rank => {
                        let mut sorted: Vec<(usize, f64)> = input.iter().copied().enumerate().filter(|(_, v)| v.is_finite()).collect();
                        sorted.sort_by(|a, b| a.1.total_cmp(&b.1));
                        let mut out = vec![f64::NAN; self.products];
                        let n = sorted.len() as f64;
                        for (rank, (product, _)) in sorted.into_iter().enumerate() {
                            out[product] = (rank as f64 + 1.0) / n - 0.5;
                        }
                        out
                    }
                }
            }
        };
        cache[index] = Some(value.clone());
        Ok(value)
    }
}

impl FactorEngine for FactorPlanEngine {
    type Error = alpha_algo::Error;

    fn update(&mut self, bar: &MarketBar) -> Result<Vec<f64>, Self::Error> {
        if bar.values.len() != self.products {
            return Err(alpha_algo::Error::InvalidParameter("plan product width mismatch".into()));
        }
        let mut cache = vec![None; self.nodes.len()];
        let mut out = Vec::with_capacity(self.outputs.len() * self.products);
        for output in self.outputs.clone() {
            out.extend(self.eval(output, &bar.values, &mut cache)?);
        }
        self.ordinal += 1;
        Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rolling_chain_and_binary_are_evaluated_in_rust() {
        let specs = vec![
            ExprSpec::Column(0),
            ExprSpec::Rolling { child: 0, window: 2, op: SessionOp::Mean, min_periods: 1, propagate_nan: true },
            ExprSpec::Const(1.0),
            ExprSpec::Binary { op: BinaryOp::Add, left: 1, right: 2 },
        ];
        let mut engine = FactorPlanEngine::new(1, specs, vec![3]).unwrap();
        let bar = |value| MarketBar::new(0, vec!["A".into()], vec![value]);
        assert_eq!(engine.update(&bar(1.0)).unwrap(), vec![2.0]);
        assert_eq!(engine.update(&bar(3.0)).unwrap(), vec![3.0]);
        assert_eq!(engine.update(&bar(5.0)).unwrap(), vec![5.0]);
    }

    #[test]
    fn since_tracks_bar_count_partition() {
        let specs = vec![
            ExprSpec::Column(0),
            ExprSpec::Since { condition: 0, count: 5, include_current: true, nearest: true, default_scope: true, default: 0.0 },
        ];
        let mut engine = FactorPlanEngine::new(1, specs, vec![1]).unwrap();
        assert_eq!(engine.update(&MarketBar::new(0, vec!["A".into()], vec![0.0])).unwrap(), vec![0.0]);
        assert_eq!(engine.update(&MarketBar::new(1, vec!["A".into()], vec![1.0])).unwrap(), vec![0.0]);
        assert_eq!(engine.update(&MarketBar::new(2, vec!["A".into()], vec![0.0])).unwrap(), vec![1.0]);
        assert_eq!(engine.update(&MarketBar::new(3, vec!["A".into()], vec![0.0])).unwrap(), vec![2.0]);
    }

    #[test]
    fn cross_sectional_rank_runs_in_rust() {
        let specs = vec![
            ExprSpec::Column(0),
            ExprSpec::Cross { op: CrossOp::Rank, child: 0 },
        ];
        let mut engine = FactorPlanEngine::new(2, specs, vec![1]).unwrap();
        let bar = MarketBar::new(0, vec!["A".into(), "B".into()], vec![1.0, 3.0]);
        assert_eq!(engine.update(&bar).unwrap(), vec![0.0, 0.5]);
    }
}
