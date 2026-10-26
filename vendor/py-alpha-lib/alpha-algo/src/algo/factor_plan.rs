//! A small stateful FactorExpr DAG evaluated entirely in Rust.
//!
//! The Python public API will serialize into this spec; the bridge consumes it
//! one `MarketBar` at a time.  No pandas/Python objects are involved.

use std::collections::VecDeque;

use crate::algo::{IntervalKernel, SessionOp};
use serde::Deserialize;



#[derive(Clone, Copy, Debug)]
pub enum BinaryOp { Add, Sub, Mul, Div, Gt, Lt, Ge, Le, Eq, Ne }

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CrossOp { ZScore, Rank }

#[derive(Clone, Debug)]
pub enum ExprSpec {
    Column(usize),
    Const(f64),
    Product(Vec<f64>),
    Rolling { child: usize, window: usize, op: SessionOp, min_periods: usize, propagate_nan: bool },
    Ema { child: usize, span: usize, min_periods: usize, propagate_nan: bool },
    MatchDistance { child: usize, predicate: crate::algo::MatchExpr, count: usize, nearest: bool, default: f64, include_current: bool },
    SessionRolling { child: usize, lookback_sessions: usize, sessions: Vec<(i64, i64, usize)>, op: SessionOp, min_periods: usize, propagate_nan: bool },
    Linreg { child: usize, window: usize, op: String, min_periods: usize, propagate_nan: bool },
    Neg { child: usize },
    Unary { op: String, child: usize },
    Binary { op: BinaryOp, left: usize, right: usize },
    Shift { child: usize, periods: usize },
    Where { condition: usize, when_true: usize, when_false: usize },
    Cross { op: CrossOp, child: usize },
    Since { condition: usize, count: usize, include_current: bool, nearest: bool, default_scope: bool, default: f64 },
    Distance { condition: usize, count: usize, include_current: bool, nearest: bool, default_scope: bool, default: f64 },
    Scope { child: usize, count: usize, op: SessionOp, min_periods: usize, propagate_nan: bool, sessions: Vec<(i64, i64, i64)> },
    Signal { child: usize, signal_ns: i64, sessions: Vec<(i64, i64, i64)>,
             basepoint: String, include_current: bool, partial: String },
}

struct LinearState {
    window: usize,
    min_periods: usize,
    propagate_nan: bool,
    ring: VecDeque<(u64, f64)>,
    count: usize,
    nan_count: usize,
    sx: f64, sy: f64, sxx: f64, syy: f64, sxy: f64,
}

impl LinearState {
    fn new(window: usize, min_periods: usize, propagate_nan: bool) -> Self {
        Self { window, min_periods, propagate_nan, ring: VecDeque::new(), count: 0, nan_count: 0, sx: 0.0, sy: 0.0, sxx: 0.0, syy: 0.0, sxy: 0.0 }
    }

    fn update(&mut self, index: u64, value: f64, op: &str) -> f64 {
        while self.ring.front().is_some_and(|(old, _)| *old + self.window as u64 <= index) {
            if let Some((old, value)) = self.ring.pop_front() {
                if value.is_finite() {
                    let x = old as f64;
                    self.sx -= x; self.sy -= value; self.sxx -= x * x; self.syy -= value * value; self.sxy -= x * value; self.count -= 1;
                } else { self.nan_count = self.nan_count.saturating_sub(1); }
            }
        }
        self.ring.push_back((index, value));
        if value.is_finite() {
            let x = index as f64;
            self.sx += x; self.sy += value; self.sxx += x * x; self.syy += value * value; self.sxy += x * value; self.count += 1;
        } else { self.nan_count += 1; }
        if (self.propagate_nan && self.nan_count > 0) || self.count < self.min_periods.max(2) {
            return f64::NAN;
        }
        let n = self.count as f64;
        let cxx = self.sxx - self.sx * self.sx / n;
        let cyy = self.syy - self.sy * self.sy / n;
        let cxy = self.sxy - self.sx * self.sy / n;
        if cxx <= 0.0 { return f64::NAN; }
        let slope = cxy / cxx;
        let intercept = (self.sy - slope * self.sx) / n;
        let sse = (self.syy - intercept * self.sy - slope * self.sxy).max(0.0);
        match op {
            "linreg_slope" => slope,
            "linreg_r2" => if cyy <= 0.0 { f64::NAN } else { 1.0 - sse / cyy },
            "linreg_resid_std" => (sse / (n - 2.0)).max(0.0).sqrt(),
            "linreg_tstat" => {
                let variance = sse / (n - 2.0);
                let standard_error = (variance / cxx).sqrt();
                if standard_error > 0.0 { slope / standard_error } else { f64::NAN }
            }
            _ => f64::NAN,
        }
    }
}

struct NodeState {
    spec: ExprSpec,
    rolling: Vec<Option<IntervalKernel>>,
    ema: Vec<Option<crate::algo::EmaState>>,
    linreg: Vec<Option<LinearState>>,
    match_history: Vec<VecDeque<(u64, f64)>>,
    history: VecDeque<Vec<f64>>,
    since_first: Vec<Option<usize>>,
    since_last: Vec<Option<usize>>,
    since_base: Vec<usize>,
    scope_base: Vec<usize>,
    signal_last: Vec<f64>,
    signal_next: Vec<Option<i64>>,
    signal_session: Option<usize>,
    signal_pending: Vec<Option<f64>>,
    signal_prev: Vec<f64>,
    scope_session: Option<usize>,
    cross_scratch: Vec<(usize, f64)>,
}

pub struct FactorPlanKernel {
    products: usize,
    nodes: Vec<NodeState>,
    outputs: Vec<usize>,
    ordinal: u64,
    timestamp_ns: i64,
    fields: usize,
    slots: Vec<Vec<f64>>,
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
                ExprSpec::Rolling { op, .. } | ExprSpec::Scope { op, .. } | ExprSpec::SessionRolling { op, .. } => (0..products)
                    .map(|_| IntervalKernel::new_explicit(*op).map(Some))
                    .collect::<Result<Vec<_>, _>>()?,
                _ => (0..products).map(|_| None).collect(),
            };
            let ema = match &spec {
                ExprSpec::Ema { span, min_periods, propagate_nan, .. } => (0..products)
                    .map(|_| crate::algo::EmaState::new(*span).ok().map(|state| state.with_semantics(*min_periods, *propagate_nan)))
                    .collect(),
                _ => (0..products).map(|_| None).collect(),
            };
            let linreg = match &spec {
                ExprSpec::Linreg { window, min_periods, propagate_nan, .. } => (0..products)
                    .map(|_| Some(LinearState::new(*window, *min_periods, *propagate_nan)))
                    .collect(),
                _ => (0..products).map(|_| None).collect(),
            };
            nodes.push(NodeState {
                spec, rolling, ema, linreg,
                match_history: (0..products).map(|_| VecDeque::new()).collect(),
                history: VecDeque::new(),
                since_first: vec![None; products],
                since_last: vec![None; products],
                since_base: vec![0; products],
                scope_base: vec![0; products],
                signal_last: vec![f64::NAN; products],
                signal_next: vec![None; products],
                signal_session: None,
                signal_pending: vec![None; products],
                signal_prev: vec![f64::NAN; products],
                scope_session: None,
                cross_scratch: Vec::new(),
            });
        }
        if outputs.iter().any(|index| *index >= nodes.len()) {
            return Err(crate::algo::Error::InvalidParameter("plan output out of range".into()));
        }
        for (index, node) in nodes.iter().enumerate() {
            let children: &[usize] = match &node.spec {
                ExprSpec::Column(_) | ExprSpec::Const(_) | ExprSpec::Product(_) => &[],
                ExprSpec::Neg { child } | ExprSpec::Unary { child, .. } | ExprSpec::Rolling { child, .. }
                | ExprSpec::SessionRolling { child, .. } | ExprSpec::MatchDistance { child, .. }
                | ExprSpec::Ema { child, .. } | ExprSpec::Linreg { child, .. }
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
                ExprSpec::Since { condition, .. } | ExprSpec::Distance { condition, .. } => {
                    if *condition >= index { return Err(crate::algo::Error::InvalidParameter("plan child must precede parent".into())); }
                    &[]
                }
            };
            if children.iter().any(|child| *child >= index) {
                return Err(crate::algo::Error::InvalidParameter("plan child must precede parent".into()));
            }
            match &node.spec {
                ExprSpec::Ema { span, .. } if *span == 0 => return Err(crate::algo::Error::InvalidParameter("ema span must be positive".into())),
                ExprSpec::Linreg { window, .. } if *window == 0 => return Err(crate::algo::Error::InvalidParameter("linreg window must be positive".into())),
                ExprSpec::Rolling { window, .. } if *window == 0 => return Err(crate::algo::Error::InvalidParameter("rolling window must be positive".into())),
                ExprSpec::Scope { count, sessions, .. } if sessions.is_empty() && *count == 0 => return Err(crate::algo::Error::InvalidParameter("scope count must be positive".into())),
                ExprSpec::Since { count, .. } | ExprSpec::Distance { count, .. } if *count == 0 => return Err(crate::algo::Error::InvalidParameter("scope count must be positive".into())),
                _ => {}
            }
        }
        let slots = vec![vec![f64::NAN; products]; nodes.len()];
        Ok(Self { products, nodes, outputs, ordinal: 0, timestamp_ns: 0, fields: 1, slots, node_keys: Vec::new() })
    }

    pub fn update(&mut self, values: &[f64]) -> Result<Vec<f64>, crate::algo::Error> {
        self.update_at(0, values)
    }

    pub fn update_at(&mut self, timestamp_ns: i64, values: &[f64]) -> Result<Vec<f64>, crate::algo::Error> {
        let mut result = Vec::with_capacity(self.outputs.len() * self.products);
        self.update_into(timestamp_ns, values, &mut result)?;
        Ok(result)
    }

    pub fn update_into(&mut self, timestamp_ns: i64, values: &[f64], result: &mut Vec<f64>) -> Result<(), crate::algo::Error> {
        self.timestamp_ns = timestamp_ns;
        if self.products == 0 || values.is_empty() || values.len() % self.products != 0 {
            return Err(crate::algo::Error::InvalidParameter("plan values must be product-major fields".into()));
        }
        self.fields = values.len() / self.products;
        let products = self.products;
        let fields = self.fields;
        let current = self.ordinal;
        for index in 0..self.nodes.len() {
            let spec = self.nodes[index].spec.clone();
            let (head, tail) = self.slots.split_at_mut(index);
            let out = &mut tail[0];
            match spec {
                ExprSpec::Product(ref values) => {
                    if values.len() != products { return Err(crate::algo::Error::InvalidParameter("product constant width mismatch".into())); }
                    out.copy_from_slice(values);
                }
                ExprSpec::Column(column) => {
                    if column >= fields { return Err(crate::algo::Error::InvalidParameter("column out of range".into())); }
                    if fields == 1 { out.copy_from_slice(values); }
                    else { for product in 0..products { out[product] = values[product * fields + column]; } }
                }
                ExprSpec::Const(value) => out.fill(value),
                ExprSpec::Neg { child } => {
                    let input = &head[child];
                    for product in 0..products { out[product] = -input[product]; }
                }
                ExprSpec::Unary { ref op, child } => {
                    let input = &head[child];
                    for product in 0..products {
                        out[product] = match op.as_str() {
                            "abs" => input[product].abs(),
                            "sign" => input[product].signum(),
                            "sqrt" => input[product].sqrt(),
                            "log" => input[product].ln(),
                            "tanh" => input[product].tanh(),
                            _ => f64::NAN,
                        };
                    }
                }
                ExprSpec::Binary { op, left, right } => {
                    let a = &head[left]; let b = &head[right];
                    for product in 0..products { out[product] = binary(op, a[product], b[product]); }
                }
                ExprSpec::Rolling { child, window, min_periods, propagate_nan, .. } => {
                    let input = &head[child];
                    let node = &mut self.nodes[index];
                    let start = current.saturating_sub(window as u64 - 1);
                    for product in 0..products {
                        let Some(state) = node.rolling[product].as_mut() else { out[product] = f64::NAN; continue };
                        state.set_semantics(min_periods, propagate_nan);
                        out[product] = state.update_explicit(start, current, input[product]);
                    }
                }
                ExprSpec::MatchDistance { child, ref predicate, count, nearest, default, include_current } => {
                    let input = &head[child];
                    let node = &mut self.nodes[index];
                    for product in 0..products {
                        let current_value = input[product];
                        let candidates: Vec<(u64, f64)> = node.match_history[product].iter().copied().collect();
                        let mut value = crate::algo::match_distance(current, current_value, &candidates, predicate, count as u64, nearest, default);
                        if include_current && predicate.eval(current_value, current_value) != 0.0 { value = 0.0; }
                        out[product] = value;
                        let history = &mut node.match_history[product];
                        history.push_back((current, current_value));
                        while history.len() > count { history.pop_front(); }
                    }
                }
                ExprSpec::SessionRolling { child, lookback_sessions, ref sessions, min_periods, propagate_nan, .. } => {
                    let input = &head[child];
                    let node = &mut self.nodes[index];
                    let current_session = sessions.iter().position(|(start, end, _)| timestamp_ns >= *start && timestamp_ns <= *end).unwrap_or(0);
                    let first_session = (current_session + 1).saturating_sub(lookback_sessions);
                    let start: u64 = sessions[..first_session].iter().map(|(_, _, bars)| *bars as u64).sum();
                    for product in 0..products {
                        let Some(state) = node.rolling[product].as_mut() else { out[product] = f64::NAN; continue };
                        state.set_semantics(min_periods, propagate_nan);
                        out[product] = state.update_explicit(start, current, input[product]);
                    }
                }
                ExprSpec::Ema { child, min_periods, propagate_nan, .. } => {
                    let input = &head[child];
                    let node = &mut self.nodes[index];
                    for product in 0..products {
                        let Some(state) = node.ema[product].as_mut() else { out[product] = f64::NAN; continue };
                        let _ = (min_periods, propagate_nan);
                        out[product] = state.update(input[product]);
                    }
                }
                ExprSpec::Linreg { child, ref op, .. } => {
                    let input = &head[child];
                    let node = &mut self.nodes[index];
                    for product in 0..products {
                        let Some(state) = node.linreg[product].as_mut() else { out[product] = f64::NAN; continue };
                        out[product] = state.update(current, input[product], op);
                    }
                }
                ExprSpec::Shift { child, periods } => {
                    let input = &head[child];
                    let node = &mut self.nodes[index];
                    let mut buffer = if node.history.len() > periods {
                        node.history.pop_front().unwrap()
                    } else {
                        vec![f64::NAN; products]
                    };
                    buffer.copy_from_slice(input);
                    node.history.push_back(buffer);
                    if node.history.len() <= periods { out.fill(f64::NAN); }
                    else { out.copy_from_slice(&node.history[0]); }
                }
                ExprSpec::Where { condition, when_true, when_false } => {
                    let c = &head[condition]; let a = &head[when_true]; let b = &head[when_false];
                    for product in 0..products { out[product] = if c[product] != 0.0 { a[product] } else { b[product] }; }
                }
                ExprSpec::Cross { op, child } => {
                    let input = &head[child];
                    let node = &mut self.nodes[index];
                    node.cross_scratch.clear();
                    node.cross_scratch.extend((0..products).filter_map(|product| input[product].is_finite().then_some((product, input[product]))));
                    if op == CrossOp::ZScore {
                        let n = node.cross_scratch.len() as f64;
                        if n < 2.0 {
                            out.fill(f64::NAN);
                        } else {
                            let mean = node.cross_scratch.iter().map(|(_, value)| value).sum::<f64>() / n;
                            let std = (node.cross_scratch.iter().map(|(_, value)| (value - mean).powi(2)).sum::<f64>() / (n - 1.0)).sqrt();
                            for product in 0..products { out[product] = if !input[product].is_finite() { f64::NAN } else if std == 0.0 { 0.0 } else { (input[product] - mean) / std }; }
                        }
                    } else {
                        node.cross_scratch.sort_unstable_by(|a, b| a.1.total_cmp(&b.1));
                        out.fill(f64::NAN);
                        let n = node.cross_scratch.len() as f64;
                        let mut start = 0;
                        while start < node.cross_scratch.len() {
                            let mut end = start + 1;
                            while end < node.cross_scratch.len() && node.cross_scratch[end].1 == node.cross_scratch[start].1 { end += 1; }
                            let rank = (start + 1 + end) as f64 / 2.0;
                            for (product, _) in &node.cross_scratch[start..end] { out[*product] = rank / n - 0.5; }
                            start = end;
                        }
                    }
                }
                ExprSpec::Since { condition, count, include_current, nearest, default_scope, default }
                | ExprSpec::Distance { condition, count, include_current, nearest, default_scope, default } => {
                    let input = &head[condition];
                    let node = &mut self.nodes[index];
                    for product in 0..products {
                        if current as usize % count == 0 { node.since_base[product] = current as usize; node.since_first[product] = None; node.since_last[product] = None; }
                        let truth = input[product].is_finite() && input[product] != 0.0;
                        if truth && include_current { if node.since_first[product].is_none() { node.since_first[product] = Some(current as usize); } node.since_last[product] = Some(current as usize); }
                        let matched = if nearest { node.since_last[product] } else { node.since_first[product] };
                        out[product] = match matched { Some(hit) => (current as usize - hit) as f64, None => if default_scope { (current as usize - node.since_base[product]) as f64 } else { default } };
                        if truth && !include_current { if node.since_first[product].is_none() { node.since_first[product] = Some(current as usize); } node.since_last[product] = Some(current as usize); }
                    }
                }
                ExprSpec::Scope { child, count, op, min_periods, propagate_nan, sessions } => {
                    let input = &head[child];
                    let node = &mut self.nodes[index];
                    if !sessions.is_empty() {
                        let session = sessions.iter().position(|(start, end, _)| timestamp_ns >= *start && timestamp_ns <= *end);
                        if session != node.scope_session { node.scope_session = session; node.scope_base.fill(current as usize); for state in node.rolling.iter_mut().flatten() { state.reset_at(current); } }
                    } else if current as usize % count == 0 { node.scope_base.fill(current as usize); }
                    for product in 0..products {
                        let Some(state) = node.rolling[product].as_mut() else { out[product] = f64::NAN; continue };
                        state.set_semantics(min_periods, propagate_nan);
                        out[product] = state.update_explicit(node.scope_base[product] as u64, current, input[product]);
                    }
                }
                ExprSpec::Signal { child, signal_ns, sessions, basepoint, include_current, partial } => {
                    let input = &head[child];
                    let node = &mut self.nodes[index];
                    let session = sessions.iter().position(|(start, end, _)| timestamp_ns >= *start && timestamp_ns <= *end);
                    if session != node.signal_session { node.signal_session = session; node.signal_last.fill(f64::NAN); node.signal_next.fill(None); node.signal_pending.fill(None); node.signal_prev.fill(f64::NAN); }
                    let session_end = session.map(|position| sessions[position].1);
                    for product in 0..products {
                        if node.signal_next[product].is_none() { let anchor = session.map_or(timestamp_ns, |position| sessions[position].2); let first = if anchor % signal_ns == 0 { anchor } else { (anchor / signal_ns + 1) * signal_ns }; node.signal_next[product] = Some(first); }
                        let next = node.signal_next[product].unwrap_or(i64::MAX);
                        let target = timestamp_ns >= next;
                        let emit_partial = partial == "emit" && session_end == Some(timestamp_ns) && timestamp_ns < next;
                        if target || emit_partial {
                            let value = if basepoint == "first" { node.signal_pending[product].unwrap_or(if include_current { input[product] } else { f64::NAN }) } else if include_current { input[product] } else { node.signal_prev[product] };
                            node.signal_last[product] = value; node.signal_pending[product] = None;
                            if target { node.signal_next[product] = Some(next + signal_ns); }
                        } else if basepoint == "first" && node.signal_pending[product].is_none() { node.signal_pending[product] = Some(input[product]); }
                        node.signal_prev[product] = input[product];
                        out[product] = node.signal_last[product];
                    }
                }
            }
        }
        result.clear();
        for output in &self.outputs { result.extend_from_slice(&self.slots[*output]); }
        self.ordinal += 1;
        Ok(())
    }
}

fn default_basepoint() -> String { "last".into() }
fn default_include_current() -> bool { true }
fn default_partial() -> String { "drop".into() }

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
enum RawMatch {
    Current,
    Candidate,
    Const { value: f64 },
    Add { a: Box<RawMatch>, b: Box<RawMatch> },
    Sub { a: Box<RawMatch>, b: Box<RawMatch> },
    Mul { a: Box<RawMatch>, b: Box<RawMatch> },
    Div { a: Box<RawMatch>, b: Box<RawMatch> },
    Abs { a: Box<RawMatch> },
    Gt { a: Box<RawMatch>, b: Box<RawMatch> },
    Lt { a: Box<RawMatch>, b: Box<RawMatch> },
    Ge { a: Box<RawMatch>, b: Box<RawMatch> },
    Le { a: Box<RawMatch>, b: Box<RawMatch> },
    Eq { a: Box<RawMatch>, b: Box<RawMatch> },
    Ne { a: Box<RawMatch>, b: Box<RawMatch> },
}

fn compile_match(raw: RawMatch) -> crate::algo::MatchExpr {
    use crate::algo::MatchExpr as M;
    match raw {
        RawMatch::Current => M::Current,
        RawMatch::Candidate => M::Candidate,
        RawMatch::Const { value } => M::Const(value),
        RawMatch::Add { a, b } => M::Add(Box::new(compile_match(*a)), Box::new(compile_match(*b))),
        RawMatch::Sub { a, b } => M::Sub(Box::new(compile_match(*a)), Box::new(compile_match(*b))),
        RawMatch::Mul { a, b } => M::Mul(Box::new(compile_match(*a)), Box::new(compile_match(*b))),
        RawMatch::Div { a, b } => M::Div(Box::new(compile_match(*a)), Box::new(compile_match(*b))),
        RawMatch::Abs { a } => M::Abs(Box::new(compile_match(*a))),
        RawMatch::Gt { a, b } => M::Gt(Box::new(compile_match(*a)), Box::new(compile_match(*b))),
        RawMatch::Lt { a, b } => M::Lt(Box::new(compile_match(*a)), Box::new(compile_match(*b))),
        RawMatch::Ge { a, b } => M::Ge(Box::new(compile_match(*a)), Box::new(compile_match(*b))),
        RawMatch::Le { a, b } => M::Le(Box::new(compile_match(*a)), Box::new(compile_match(*b))),
        RawMatch::Eq { a, b } => M::Eq(Box::new(compile_match(*a)), Box::new(compile_match(*b))),
        RawMatch::Ne { a, b } => M::Ne(Box::new(compile_match(*a)), Box::new(compile_match(*b))),
    }
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum RawNode {
    Column { index: usize },
    Const { value: f64 },
    Product { values: Vec<f64> },
    Rolling { child: usize, window: usize, op: String, min_periods: usize,
              propagate_nan: bool, #[serde(default)] quantile: Option<f64> },
    Scope { child: usize, count: usize, op: String, min_periods: usize, propagate_nan: bool,
            #[serde(default)] sessions: Vec<[i64; 3]> },
    SessionRolling { child: usize, lookback_sessions: usize, sessions: Vec<[i64; 3]>, op: String,
                     min_periods: usize, propagate_nan: bool },
    MatchDistance { child: usize, predicate: RawMatch, count: usize, nearest: bool,
                    default: f64, #[serde(default = "default_include_current")] include_current: bool },
    Binary { op: String, left: usize, right: usize },
    Neg { child: usize },
    Unary { op: String, child: usize },
    Shift { child: usize, periods: usize },
    Where { condition: usize, when_true: usize, when_false: usize },
    Cross { op: String, child: usize },
    Since { condition: usize, count: usize, include_current: bool, nearest: bool,
            default_scope: bool, default: f64 },
    Distance { condition: usize, count: usize, include_current: bool, nearest: bool,
               default_scope: bool, default: f64 },
    Signal { child: usize, signal_ns: i64, #[serde(default)] sessions: Vec<[i64; 3]>,
             #[serde(default = "default_basepoint")] basepoint: String,
             #[serde(default = "default_include_current")] include_current: bool,
             #[serde(default = "default_partial")] partial: String },
}

#[derive(Deserialize)]
struct RawPlan { #[serde(default)] keys: Vec<String>, nodes: Vec<RawNode>, outputs: Vec<usize> }

fn session_op(name: &str, quantile: Option<f64>) -> Result<SessionOp, crate::algo::Error> {
    Ok(match name {
        "sum" => SessionOp::Sum, "mean" => SessionOp::Mean,
        "var" => SessionOp::Var, "std" => SessionOp::Std,
        "min" => SessionOp::Min, "max" => SessionOp::Max,
        "skew" => SessionOp::Skew, "argmin" => SessionOp::Argmin,
        "argmax" => SessionOp::Argmax, "argmin_raw" => SessionOp::ArgminRaw,
        "argmax_raw" => SessionOp::ArgmaxRaw, "rank" => SessionOp::Rank,
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
                RawNode::Product { values } => ExprSpec::Product(values),
                RawNode::Rolling { child, window, op, min_periods, propagate_nan, quantile } => {
                    if op == "ema" {
                        ExprSpec::Ema { child, span: window, min_periods, propagate_nan }
                    } else if op.starts_with("linreg_") {
                        ExprSpec::Linreg { child, window, op, min_periods, propagate_nan }
                    } else {
                        ExprSpec::Rolling { child, window, op: session_op(&op, quantile)?, min_periods, propagate_nan }
                    }
                }
                RawNode::MatchDistance { child, predicate, count, nearest, default, include_current } =>
                    ExprSpec::MatchDistance { child, predicate: compile_match(predicate), count, nearest, default, include_current },
                RawNode::SessionRolling { child, lookback_sessions, sessions, op, min_periods, propagate_nan } =>
                    ExprSpec::SessionRolling { child, lookback_sessions,
                        sessions: sessions.into_iter().map(|item| (item[0], item[1], item[2] as usize)).collect(),
                        op: session_op(&op, None)?, min_periods, propagate_nan },
                RawNode::Scope { child, count, op, min_periods, propagate_nan, sessions } =>
                    ExprSpec::Scope { child, count, op: session_op(&op, None)?, min_periods, propagate_nan,
                        sessions: sessions.into_iter().map(|item| (item[0], item[1], item[2])).collect() },
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
                RawNode::Unary { op, child } => ExprSpec::Unary { op, child },
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
                RawNode::Distance { condition, count, include_current, nearest, default_scope, default } =>
                    ExprSpec::Distance { condition, count, include_current, nearest, default_scope, default },
                RawNode::Signal { child, signal_ns, sessions, basepoint, include_current, partial } =>
                    ExprSpec::Signal { child, signal_ns,
                        sessions: sessions.into_iter().map(|item| (item[0], item[1], item[2])).collect(),
                        basepoint, include_current, partial },
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

#[cfg(test)]
mod match_plan_tests {
    use super::*;

    #[test]
    fn match_distance_compiles_to_plan_json() {
        let json = r#"{"columns":["C"],"nodes":[
          {"kind":"column","index":0},
          {"kind":"match_distance","child":0,"count":3,"nearest":true,"default":9.0,"include_current":true,
           "predicate":{"op":"ge","a":{"op":"sub","a":{"op":"current"},"b":{"op":"candidate"}},"b":{"op":"const","value":1.5}}}
        ],"outputs":[1]}"#;
        let mut kernel = FactorPlanKernel::from_spec_json(json, 1).unwrap();
        assert_eq!(kernel.update(&[10.0]).unwrap(), vec![9.0]);
        assert_eq!(kernel.update(&[12.0]).unwrap(), vec![1.0]);
    }
}
