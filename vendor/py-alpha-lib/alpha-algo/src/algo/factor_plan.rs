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
    Neg { child: usize },
    Binary { op: BinaryOp, left: usize, right: usize },
    Shift { child: usize, periods: usize },
    Where { condition: usize, when_true: usize, when_false: usize },
    Cross { op: CrossOp, child: usize },
    Since { condition: usize, count: usize, include_current: bool, nearest: bool, default_scope: bool, default: f64 },
    Scope { child: usize, count: usize, op: SessionOp, min_periods: usize, propagate_nan: bool, sessions: Vec<(i64, i64)> },
    Signal { child: usize, signal_ns: i64, sessions: Vec<(i64, i64)> },
}

struct NodeState {
    spec: ExprSpec,
    rolling: Vec<Option<IntervalKernel>>,
    history: VecDeque<Vec<f64>>,
    since_first: Vec<Option<usize>>,
    since_last: Vec<Option<usize>>,
    since_base: Vec<usize>,
    scope_base: Vec<usize>,
    signal_last: Vec<f64>,
    signal_next: Vec<Option<i64>>,
    signal_session: Option<usize>,
    scope_session: Option<usize>,
}

pub struct FactorPlanKernel {
    products: usize,
    nodes: Vec<NodeState>,
    outputs: Vec<usize>,
    ordinal: u64,
    timestamp_ns: i64,
    node_keys: Vec<String>,
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
            nodes.push(NodeState {
                spec, rolling, history: VecDeque::new(),
                since_first: vec![None; products],
                since_last: vec![None; products],
                since_base: vec![0; products],
                scope_base: vec![0; products],
                signal_last: vec![f64::NAN; products],
                signal_next: vec![None; products],
                signal_session: None,
                scope_session: None,
            });
        }
        if outputs.iter().any(|index| *index >= nodes.len()) {
            return Err(crate::algo::Error::InvalidParameter("plan output out of range".into()));
        }
        for (index, node) in nodes.iter().enumerate() {
            let children: &[usize] = match &node.spec {
                ExprSpec::Column(_) | ExprSpec::Const(_) => &[],
                ExprSpec::Neg { child } | ExprSpec::Rolling { child, .. }
                | ExprSpec::Shift { child, .. } | ExprSpec::Cross { child, .. }
                | ExprSpec::Scope { child, .. } | ExprSpec::Signal { child, .. } => std::slice::from_ref(child),
                ExprSpec::Binary { left, right, .. } => {
                    if *left >= index || *right >= index { return Err(crate::algo::Error::InvalidParameter("plan child must precede parent".into())); }
                    &[]
                }
                ExprSpec::Where { condition, when_true, when_false } => {
                    if *condition >= index || *when_true >= index || *when_false >= index { return Err(crate::algo::Error::InvalidParameter("plan child must precede parent".into())); }
                    &[]
                }
                ExprSpec::Since { condition, .. } => {
                    if *condition >= index { return Err(crate::algo::Error::InvalidParameter("plan child must precede parent".into())); }
                    &[]
                }
            };
            if children.iter().any(|child| *child >= index) {
                return Err(crate::algo::Error::InvalidParameter("plan child must precede parent".into()));
            }
            match &node.spec {
                ExprSpec::Rolling { window, .. } if *window == 0 => return Err(crate::algo::Error::InvalidParameter("rolling window must be positive".into())),
                ExprSpec::Scope { count, sessions, .. } if sessions.is_empty() && *count == 0 => return Err(crate::algo::Error::InvalidParameter("scope count must be positive".into())),
                ExprSpec::Since { count, .. } if *count == 0 => return Err(crate::algo::Error::InvalidParameter("scope count must be positive".into())),
                _ => {}
            }
        }
        Ok(Self { products, nodes, outputs, ordinal: 0, timestamp_ns: 0, node_keys: Vec::new() })
    }

    fn eval(&mut self, index: usize, columns: &[f64], cache: &mut [Option<Vec<f64>>]) -> Result<Vec<f64>, crate::algo::Error> {
        if let Some(value) = &cache[index] { return Ok(value.clone()); }
        let spec = self.nodes[index].spec.clone();
        let value = match spec {
            ExprSpec::Column(column) => {
                if column >= columns.len() {
                    return Err(crate::algo::Error::InvalidParameter("column out of range".into()));
                }
                if columns.len() == self.products {
                    columns.to_vec()
                } else {
                    vec![columns[column]; self.products]
                }
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
            ExprSpec::Neg { child } => self.eval(child, columns, cache)?.iter().map(|value| -*value).collect(),
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
            ExprSpec::Signal { child, signal_ns, sessions } => {
                let input = self.eval(child, columns, cache)?;
                let timestamp = self.timestamp_ns;
                let node = &mut self.nodes[index];
                let session = sessions.iter().position(|(start, end)| timestamp >= *start && timestamp <= *end);
                if session != node.signal_session {
                    node.signal_session = session;
                    node.signal_last.fill(f64::NAN);
                    node.signal_next.fill(None);
                }
                for product in 0..self.products {
                    if node.signal_next[product].is_none() {
                        let anchor = session.map_or(timestamp, |position| sessions[position].0);
                        let first = if anchor % signal_ns == 0 { anchor } else { (anchor / signal_ns + 1) * signal_ns };
                        node.signal_next[product] = Some(first);
                    }
                    if timestamp >= node.signal_next[product].unwrap_or(i64::MAX) {
                        node.signal_last[product] = input[product];
                        node.signal_next[product] = Some(node.signal_next[product].unwrap_or(timestamp) + signal_ns);
                    }
                }
                node.signal_last.clone()
            }
            ExprSpec::Scope { child, count, op, min_periods, propagate_nan, sessions } => {
                let input = self.eval(child, columns, cache)?;
                let current = self.ordinal;
                let timestamp = self.timestamp_ns;
                let node = &mut self.nodes[index];
                if !sessions.is_empty() {
                    let session = sessions.iter().position(|(start, end)| timestamp >= *start && timestamp <= *end);
                    if session != node.scope_session {
                        node.scope_session = session;
                        node.scope_base.fill(current as usize);
                        for state in node.rolling.iter_mut().flatten() { state.reset_at(current); }
                    }
                } else if current as usize % count == 0 {
                    node.scope_base.fill(current as usize);
                }
                input.iter().enumerate().map(|(product, value)| {
                    let Some(state) = node.rolling[product].as_mut() else { return f64::NAN };
                    state.set_semantics(min_periods, propagate_nan);
                    state.update_explicit(node.scope_base[product] as u64, current, *value)
                }).collect()
            }
            ExprSpec::Since { condition, count, include_current, nearest, default_scope, default } => {
                let condition = self.eval(condition, columns, cache)?;
                let mut out = vec![f64::NAN; self.products];
                for product in 0..self.products {
                    let node = &mut self.nodes[index];
                    if self.ordinal as usize % count == 0 {
                        node.since_base[product] = self.ordinal as usize;
                        node.since_first[product] = None;
                        node.since_last[product] = None;
                    }
                    let truth = condition[product].is_finite() && condition[product] != 0.0;
                    if truth && include_current {
                        if node.since_first[product].is_none() { node.since_first[product] = Some(self.ordinal as usize); }
                        node.since_last[product] = Some(self.ordinal as usize);
                    }
                    let matched = if nearest { node.since_last[product] } else { node.since_first[product] };
                    out[product] = match matched {
                        Some(hit) => (self.ordinal as usize - hit) as f64,
                        None => if default_scope { (self.ordinal as usize - node.since_base[product]) as f64 } else { default },
                    };
                    if truth && !include_current {
                        if node.since_first[product].is_none() { node.since_first[product] = Some(self.ordinal as usize); }
                        node.since_last[product] = Some(self.ordinal as usize);
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
        self.update_at(0, values)
    }

    pub fn update_at(&mut self, timestamp_ns: i64, values: &[f64]) -> Result<Vec<f64>, crate::algo::Error> {
        self.timestamp_ns = timestamp_ns;
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
    Scope { child: usize, count: usize, op: String, min_periods: usize, propagate_nan: bool,
            #[serde(default)] sessions: Vec<[i64; 2]> },
    Binary { op: String, left: usize, right: usize },
    Neg { child: usize },
    Shift { child: usize, periods: usize },
    Where { condition: usize, when_true: usize, when_false: usize },
    Cross { op: String, child: usize },
    Since { condition: usize, count: usize, include_current: bool, nearest: bool,
            default_scope: bool, default: f64 },
    Signal { child: usize, signal_ns: i64, #[serde(default)] sessions: Vec<[i64; 2]> },
}

#[derive(Deserialize)]
struct RawPlan { #[serde(default)] keys: Vec<String>, nodes: Vec<RawNode>, outputs: Vec<usize> }

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
                RawNode::Scope { child, count, op, min_periods, propagate_nan, sessions } =>
                    ExprSpec::Scope { child, count, op: session_op(&op, None)?, min_periods, propagate_nan,
                        sessions: sessions.into_iter().map(|pair| (pair[0], pair[1])).collect() },
                RawNode::Binary { op, left, right } => ExprSpec::Binary {
                    op: match op.as_str() {
                        "add" => BinaryOp::Add, "sub" => BinaryOp::Sub, "mul" => BinaryOp::Mul,
                        "div" => BinaryOp::Div, "gt" => BinaryOp::Gt, "lt" => BinaryOp::Lt,
                        "ge" => BinaryOp::Ge, "le" => BinaryOp::Le, "eq" => BinaryOp::Eq,
                        "ne" => BinaryOp::Ne,
                        other => return Err(crate::algo::Error::InvalidParameter(format!("unsupported binary op {other}"))),
                    }, left, right,
                },
                RawNode::Neg { child } => ExprSpec::Neg { child },
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
                RawNode::Signal { child, signal_ns, sessions } =>
                    ExprSpec::Signal { child, signal_ns, sessions: sessions.into_iter().map(|pair| (pair[0], pair[1])).collect() },
            });
        }
        let mut plan = Self::new(products, specs, raw.outputs)?;
        plan.node_keys = raw.keys;
        Ok(plan)
    }

    pub fn node_keys(&self) -> &[String] { &self.node_keys }
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

#[cfg(test)]
mod audit_tests {
    use super::*;

    #[test]
    fn neg_is_not_zero() {
        let mut kernel = FactorPlanKernel::new(1, vec![
            ExprSpec::Column(0), ExprSpec::Neg { child: 0 },
        ], vec![1]).unwrap();
        assert_eq!(kernel.update(&[3.0]).unwrap(), vec![-3.0]);
    }

    #[test]
    fn column_keeps_each_product_value() {
        let mut kernel = FactorPlanKernel::new(2, vec![ExprSpec::Column(0)], vec![0]).unwrap();
        assert_eq!(kernel.update(&[2.0, 4.0]).unwrap(), vec![2.0, 4.0]);
    }

    #[test]
    fn two_since_nodes_do_not_share_state() {
        let mut kernel = FactorPlanKernel::new(1, vec![
            ExprSpec::Column(0),
            ExprSpec::Since { condition: 0, count: 10, include_current: true, nearest: true, default_scope: false, default: 0.0 },
            ExprSpec::Since { condition: 0, count: 10, include_current: true, nearest: false, default_scope: false, default: 0.0 },
        ], vec![1, 2]).unwrap();
        assert_eq!(kernel.update(&[1.0]).unwrap(), vec![0.0, 0.0]);
        assert_eq!(kernel.update(&[0.0]).unwrap(), vec![1.0, 1.0]);
        assert_eq!(kernel.update(&[0.0]).unwrap(), vec![2.0, 2.0]);
        assert_eq!(kernel.update(&[1.0]).unwrap(), vec![0.0, 3.0]);
        assert_eq!(kernel.update(&[0.0]).unwrap(), vec![1.0, 4.0]);
    }

    #[test]
    fn plan_json_preserves_structural_keys() {
        let json = r#"{"columns":["CLOSE"],"keys":["k0","k1"],"nodes":[{"kind":"column","index":0},{"kind":"column","index":0}],"outputs":[1]}"#;
        let kernel = FactorPlanKernel::from_spec_json(json, 1).unwrap();
        assert_eq!(kernel.node_keys(), &["k0".to_string(), "k1".to_string()]);
    }

    #[test]
    fn invalid_child_index_is_an_error() {
        let result = FactorPlanKernel::new(1, vec![
            ExprSpec::Neg { child: 9 },
        ], vec![0]);
        assert!(result.is_err());
    }
}

#[cfg(test)]
mod timeline_tests {
    use super::*;

    #[test]
    fn asof_mapping_never_uses_future_values() {
        let source = [10_i64, 20, 30];
        let target = [5_i64, 10, 15, 20, 25, 30];
        // The helper lives on PanelPlan.
        let positions = crate::algo::PanelPlan::asof_indices(&source, &target).unwrap();
        assert_eq!(positions, vec![-1, 0, 0, 1, 1, 2]);
    }
}
