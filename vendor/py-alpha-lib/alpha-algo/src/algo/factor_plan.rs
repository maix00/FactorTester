//! A small stateful FactorExpr DAG evaluated entirely in Rust.
//!
//! The Python public API will serialize into this spec; the bridge consumes it
//! one `MarketBar` at a time.  No pandas/Python objects are involved.

use std::collections::VecDeque;

use crate::algo::{IntervalKernel, SessionOp};
use serde::Deserialize;



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
    Scope { child: usize, count: usize, op: SessionOp, min_periods: usize, propagate_nan: bool },
}

struct NodeState {
    spec: ExprSpec,
    rolling: Vec<Option<IntervalKernel>>,
    history: VecDeque<Vec<f64>>,
}

pub struct FactorPlanKernel {
    products: usize,
    nodes: Vec<NodeState>,
    outputs: Vec<usize>,
    ordinal: u64,
    since_first: Vec<Option<usize>>,
    since_last: Vec<Option<usize>>,
    since_base: Vec<usize>,
    scope_bases: Vec<usize>,
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

impl FactorPlanKernel {
    pub fn new(products: usize, specs: Vec<ExprSpec>, outputs: Vec<usize>) -> Result<Self, crate::algo::Error> {
        if products == 0 || specs.is_empty() || outputs.is_empty() {
            return Err(crate::algo::Error::InvalidParameter("plan requires products, nodes and outputs".into()));
        }
        let mut nodes = Vec::with_capacity(specs.len());
        for spec in specs {
            let rolling = match &spec {
                ExprSpec::Rolling { op, .. } | ExprSpec::Scope { op, .. } => (0..products)
                    .map(|_| IntervalKernel::new_explicit(*op).map(Some))
                    .collect::<Result<Vec<_>, _>>()?,
                _ => (0..products).map(|_| None).collect(),
            };
            nodes.push(NodeState { spec, rolling, history: VecDeque::new() });
        }
        if outputs.iter().any(|index| *index >= nodes.len()) {
            return Err(crate::algo::Error::InvalidParameter("plan output out of range".into()));
        }
        Ok(Self {
            products, nodes, outputs, ordinal: 0,
            since_first: vec![None; products],
            since_last: vec![None; products],
            since_base: vec![0; products],
            scope_bases: vec![0; products],
        })
    }

    fn eval(&mut self, index: usize, columns: &[f64], cache: &mut [Option<Vec<f64>>]) -> Result<Vec<f64>, crate::algo::Error> {
        if let Some(value) = &cache[index] { return Ok(value.clone()); }
        let spec = self.nodes[index].spec.clone();
        let value = match spec {
            ExprSpec::Column(column) => {
                if column >= columns.len() { return Err(crate::algo::Error::InvalidParameter("column out of range".into())); }
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
            ExprSpec::Scope { child, count, op, min_periods, propagate_nan } => {
                let input = self.eval(child, columns, cache)?;
                let current = self.ordinal;
                let node = &mut self.nodes[index];
                input.iter().enumerate().map(|(product, value)| {
                    if current as usize % count == 0 { self.scope_bases[product] = current as usize; }
                    let Some(state) = node.rolling[product].as_mut() else { return f64::NAN };
                    state.set_semantics(min_periods, propagate_nan);
                    state.update_explicit(self.scope_bases[product] as u64, current, *value)
                }).collect()
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

impl FactorPlanKernel {
    pub fn update(&mut self, values: &[f64]) -> Result<Vec<f64>, crate::algo::Error> {
        if values.len() != self.products {
            return Err(crate::algo::Error::InvalidParameter("plan product width mismatch".into()));
        }
        let mut cache = vec![None; self.nodes.len()];
        let mut out = Vec::with_capacity(self.outputs.len() * self.products);
        for output in self.outputs.clone() {
            out.extend(self.eval(output, values, &mut cache)?);
        }
        self.ordinal += 1;
        Ok(out)
    }
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum RawNode {
    Column { index: usize },
    Const { value: f64 },
    Rolling { child: usize, window: usize, op: String, min_periods: usize,
              propagate_nan: bool, #[serde(default)] quantile: Option<f64> },
    Scope { child: usize, count: usize, op: String, min_periods: usize, propagate_nan: bool },
    Binary { op: String, left: usize, right: usize },
    Neg { child: usize },
    Shift { child: usize, periods: usize },
    Where { condition: usize, when_true: usize, when_false: usize },
    Cross { op: String, child: usize },
    Since { condition: usize, count: usize, include_current: bool, nearest: bool,
            default_scope: bool, default: f64 },
}

#[derive(Deserialize)]
struct RawPlan { nodes: Vec<RawNode>, outputs: Vec<usize> }

fn session_op(name: &str, quantile: Option<f64>) -> Result<SessionOp, crate::algo::Error> {
    Ok(match name {
        "sum" => SessionOp::Sum, "mean" => SessionOp::Mean,
        "var" => SessionOp::Var, "std" => SessionOp::Std,
        "min" => SessionOp::Min, "max" => SessionOp::Max,
        "skew" => SessionOp::Skew, "argmin" => SessionOp::Argmin,
        "argmax" => SessionOp::Argmax, "rank" => SessionOp::Rank,
        "mad" => SessionOp::Mad, "median" => SessionOp::Quantile(0.5),
        "quantile" => SessionOp::Quantile(quantile.unwrap_or(0.5)),
        other => return Err(crate::algo::Error::InvalidParameter(format!("unsupported rolling op {other}"))),
    })
}

impl FactorPlanKernel {
    pub fn from_spec_json(json: &str, products: usize) -> Result<Self, crate::algo::Error> {
        let raw: RawPlan = serde_json::from_str(json)
            .map_err(|error| crate::algo::Error::InvalidParameter(error.to_string()))?;
        let mut specs = Vec::with_capacity(raw.nodes.len());
        for node in raw.nodes {
            specs.push(match node {
                RawNode::Column { index } => ExprSpec::Column(index),
                RawNode::Const { value } => ExprSpec::Const(value),
                RawNode::Rolling { child, window, op, min_periods, propagate_nan, quantile } => {
                    ExprSpec::Rolling { child, window, op: session_op(&op, quantile)?, min_periods, propagate_nan }
                }
                RawNode::Scope { child, count, op, min_periods, propagate_nan } =>
                    ExprSpec::Scope { child, count, op: session_op(&op, None)?, min_periods, propagate_nan },
                RawNode::Binary { op, left, right } => ExprSpec::Binary {
                    op: match op.as_str() {
                        "add" => BinaryOp::Add, "sub" => BinaryOp::Sub, "mul" => BinaryOp::Mul,
                        "div" => BinaryOp::Div, "gt" => BinaryOp::Gt, "lt" => BinaryOp::Lt,
                        "ge" => BinaryOp::Ge, "le" => BinaryOp::Le, "eq" => BinaryOp::Eq,
                        "ne" => BinaryOp::Ne,
                        other => return Err(crate::algo::Error::InvalidParameter(format!("unsupported binary op {other}"))),
                    }, left, right,
                },
                RawNode::Neg { child } => ExprSpec::Binary { op: BinaryOp::Sub, left: child, right: child },
                RawNode::Shift { child, periods } => ExprSpec::Shift { child, periods },
                RawNode::Where { condition, when_true, when_false } => ExprSpec::Where { condition, when_true, when_false },
                RawNode::Cross { op, child } => ExprSpec::Cross {
                    op: match op.as_str() {
                        "zscore" => CrossOp::ZScore, "rank" => CrossOp::Rank,
                        other => return Err(crate::algo::Error::InvalidParameter(format!("unsupported cross op {other}"))),
                    }, child,
                },
                RawNode::Since { condition, count, include_current, nearest, default_scope, default } =>
                    ExprSpec::Since { condition, count, include_current, nearest, default_scope, default },
            });
        }
        Self::new(products, specs, raw.outputs)
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
        let mut engine = FactorPlanKernel::new(1, specs, vec![3]).unwrap();
        assert_eq!(engine.update(&[1.0]).unwrap(), vec![2.0]);
        assert_eq!(engine.update(&[3.0]).unwrap(), vec![3.0]);
        assert_eq!(engine.update(&[5.0]).unwrap(), vec![5.0]);
    }

    #[test]
    fn plan_is_deserialized_from_public_api_json() {
        let json = r#"{"columns":["CLOSE"],"nodes":[{"kind":"column","index":0},{"kind":"rolling","child":0,"window":2,"op":"mean","min_periods":1,"propagate_nan":true}],"outputs":[1]}"#;
        let mut engine = FactorPlanKernel::from_spec_json(json, 1).unwrap();
        assert_eq!(engine.update(&[1.0]).unwrap(), vec![1.0]);
        assert_eq!(engine.update(&[3.0]).unwrap(), vec![2.0]);
    }

    #[test]
    fn since_tracks_bar_count_partition() {
        let specs = vec![
            ExprSpec::Column(0),
            ExprSpec::Since { condition: 0, count: 5, include_current: true, nearest: true, default_scope: true, default: 0.0 },
        ];
        let mut engine = FactorPlanKernel::new(1, specs, vec![1]).unwrap();
        assert_eq!(engine.update(&[0.0]).unwrap(), vec![0.0]);
        assert_eq!(engine.update(&[1.0]).unwrap(), vec![0.0]);
        assert_eq!(engine.update(&[0.0]).unwrap(), vec![1.0]);
        assert_eq!(engine.update(&[0.0]).unwrap(), vec![2.0]);
    }

    #[test]
    fn cross_sectional_rank_runs_in_rust() {
        let specs = vec![
            ExprSpec::Column(0),
            ExprSpec::Cross { op: CrossOp::Rank, child: 0 },
        ];
        let mut engine = FactorPlanKernel::new(2, specs, vec![1]).unwrap();
        assert_eq!(engine.update(&[1.0, 3.0]).unwrap(), vec![0.0, 0.5]);
    }
}
