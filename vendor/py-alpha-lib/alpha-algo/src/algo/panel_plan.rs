// Copyright 2026 MSD-RS Project LiJia
// SPDX-License-Identifier: BSD-2-Clause
//! Product-major matrix DAG.
//! Leaves borrow NumPy; last-use releases intermediates.
type Result<T> = std::result::Result<T, crate::algo::Error>;
use std::{borrow::Cow, collections::{HashMap, VecDeque}};

use rayon::prelude::*;

struct Grid { times: Vec<i64>, days: Vec<i64>, observed: Vec<u8> }
struct Node { op: String, children: Vec<usize>, params: Vec<f64>, indices: Vec<i64>, grid: usize }
enum Data<'a> { Scalar(f64), Product(Vec<f64>), Panel(Cow<'a, [f64]>) }
struct Value<'a> { data: Data<'a>, rows: usize, width: usize }
impl Value<'_> {
    fn at(&self, product: usize, row: usize) -> f64 {
        match &self.data {
            Data::Scalar(v) => *v,
            Data::Product(v) => v[product],
            Data::Panel(v) => v[if self.width == 1 { row } else { product * self.rows + row }],
        }
    }
    fn output(self, width: usize) -> Vec<f64> {
        match self.data {
            Data::Panel(v) => v.into_owned(),
            Data::Scalar(v) => vec![v; width * self.rows],
            Data::Product(v) => v.into_iter().flat_map(|v| std::iter::repeat_n(v, self.rows)).collect(),
        }
    }
}
fn error(message: impl Into<String>) -> crate::algo::Error { crate::algo::Error::InvalidParameter(message.into()) }
fn unary(op: &str, x: f64) -> f64 {
    match op { "neg" => -x, "abs" => x.abs(), "sign" => if x == 0.0 { 0.0 } else { x.signum() },
        "sqrt" => x.sqrt(), "log" => x.ln(), "tanh" => x.tanh(), "not" => f64::from(x == 0.0), _ => f64::NAN }
}
fn binary(op: &str, x: f64, y: f64) -> f64 {
    match op { "add" => x+y, "sub" => x-y, "mul" => x*y, "div" => x/y, "pow" => x.powf(y),
        "max" => if x.is_nan() || y.is_nan() { f64::NAN } else { x.max(y) },
        "min" => if x.is_nan() || y.is_nan() { f64::NAN } else { x.min(y) },
        "gt" => f64::from(x>y), "lt" => f64::from(x<y), "ge" => f64::from(x>=y),
        "le" => f64::from(x<=y), "eq" => f64::from(x==y), "ne" => f64::from(x!=y),
        "and" => f64::from(x!=0.0 && y!=0.0), "or" => f64::from(x!=0.0 || y!=0.0), _ => f64::NAN }
}
fn ranks(values: &[(usize, f64)], ordinal: bool, descending: bool, priorities: &[i64]) -> Vec<(usize,f64)> {
    let mut sorted = values.to_vec();
    sorted.sort_by(|a,b| {
        let order = a.1.partial_cmp(&b.1).unwrap();
        let order = if descending { order.reverse() } else { order };
        order.then_with(|| priorities[a.0].cmp(&priorities[b.0]))
    });
    let mut out=Vec::with_capacity(sorted.len()); let mut i=0;
    while i<sorted.len() {
        let mut j=i+1;
        if !ordinal { while j<sorted.len() && sorted[j].1==sorted[i].1 { j+=1; } }
        let rank=if ordinal {(i+1) as f64} else {(i+1+j) as f64/2.0};
        for &(g,_) in &sorted[i..j] { out.push((g,rank)); } i=j;
    } out
}
fn session_op(op: &str, q: f64) -> Result<crate::algo::SessionOp> {
    use crate::algo::SessionOp::*;
    Ok(match op { "mean"=>Mean,"sum"=>Sum,"var"=>Var,"std"=>Std,"min"=>Min,"max"=>Max,
        "argmin"=>Argmin,"argmax"=>Argmax,"argmin_raw"=>ArgminRaw,"argmax_raw"=>ArgmaxRaw,
        "rank"=>Rank,"mad"=>Mad,"skew"=>Skew,"median"=>Quantile(0.5),"quantile"=>Quantile(q),
        _=>return Err(error(format!("unsupported interval operation {op}"))) })
}

pub struct PanelPlan { nodes: Vec<Node>, grids: Vec<Grid> }
impl PanelPlan {
    pub fn new() -> Self { Self { nodes: vec![], grids: vec![] } }
    pub fn grid(&mut self, times: &[i64], days: &[i64], observed: &[u8]) -> Result<usize> {
        if times.len()!=days.len() { return Err(error("grid time/day length mismatch")); }
        if let Some(index) = self.grids.iter().position(|grid|
            grid.times == times && grid.days == days && grid.observed == observed
        ) { return Ok(index); }
        self.grids.push(Grid { times:times.to_vec(), days:days.to_vec(), observed:observed.to_vec() });
        Ok(self.grids.len()-1)
    }
    pub fn add(&mut self, op: String, children: Vec<usize>, params: Vec<f64>, indices: Vec<i64>, grid: usize) -> Result<usize> {
        if grid>=self.grids.len() || children.iter().any(|&c|c>=self.nodes.len()) { return Err(error("invalid grid or non-topological child")); }
        let valid=matches!(op.as_str(),"column"|"const"|"product"|"bar_count"|"reindex"|"where"|"shift"|"since"|"distance"|"term"|
            "neg"|"abs"|"sign"|"sqrt"|"log"|"tanh"|"not"|"add"|"sub"|"mul"|"div"|"pow"|"max"|"min"|
            "gt"|"lt"|"ge"|"le"|"eq"|"ne"|"and"|"or") || op.starts_with("rolling:") || op.starts_with("scope:") || op.starts_with("cross:") || op.starts_with("session_rolling:");
        if !valid { return Err(error(format!("unknown plan operation {op}"))); }
        if op == "bar_count" && (!children.is_empty() || indices.len() != 2 || indices[0] > indices[1]) {
            return Err(error("bar_count requires ordered inclusive bounds and no children"));
        }
        self.nodes.push(Node {op,children,params,indices,grid}); Ok(self.nodes.len()-1)
    }
    pub fn asof_indices(source: &[i64], target: &[i64]) -> Result<Vec<i64>> {
        let mut order:Vec<(i64,usize)>=source.iter().copied().enumerate().map(|(i,t)|(t,i)).collect();
        if source.windows(2).any(|w|w[0]>w[1]) { order.sort_by_key(|&(t,i)|(t,i)); }
        if target.windows(2).all(|w|w[0]<=w[1]) {
            let mut j=0; return Ok(target.iter().map(|&t| { while j<order.len()&&order[j].0<=t {j+=1;} if j==0 {-1} else {order[j-1].1 as i64} }).collect());
        }
        Ok(target.iter().map(|&t| {let j=order.partition_point(|&(s,_)|s<=t); if j==0 {-1} else {order[j-1].1 as i64}}).collect())
    }
    pub fn signal_indices(keys: &[i64], times: &[i64], multiple: usize, basepoint: &str, mask: Vec<bool>, gap: Option<i64>) -> Result<Vec<usize>> {
        if keys.len()!=times.len() || multiple==0 {return Err(error("invalid signal grid"));}
        let mut base=vec![false;keys.len()];
        if basepoint=="mask" { if mask.len()!=keys.len() {return Err(error("basepoint mask length mismatch"));} base=mask; }
        else if basepoint=="first" || basepoint=="last" {
            let mut positions=HashMap::new();
            for (i,&key) in keys.iter().enumerate() { if basepoint=="first" { positions.entry(key).or_insert(i); } else { positions.insert(key,i); } }
            for &i in positions.values() {base[i]=true;}
        } else {return Err(error("basepoint must be first, last or mask"));}
        if !base.iter().any(|v|*v) {let mut positions=HashMap::new();for(i,&key)in keys.iter().enumerate(){positions.insert(key,i);}for &i in positions.values(){base[i]=true;}}
        let(mut ordinal,mut start)=(0,0);let mut output=vec![];
        for i in 0..keys.len() {
            if gap.is_some_and(|g|i>0 && times[i]-times[i-1]>=g) {start=i;}
            if base[i] {if gap.is_some() {if (i-start+1)%multiple==0 {output.push(i);}} else {ordinal+=1;if ordinal%multiple==0 {output.push(i);}}}
        } Ok(output)
    }
    pub fn execute_panel(&self, columns: &[&[f64]], outputs: &[usize], products: usize) -> Result<Vec<Vec<f64>>> {
        if products==0 || outputs.iter().any(|&o|o>=self.nodes.len()) {return Err(error("invalid plan output/products"));}
        self.execute(columns, outputs, products)
    }
}

impl PanelPlan {
    pub fn execute(&self, inputs: &[&[f64]], outputs: &[usize], products:usize) -> Result<Vec<Vec<f64>>> {
        let mut uses=vec![0usize;self.nodes.len()];
        for node in &self.nodes {for &c in &node.children {uses[c]+=1;}}
        for &o in outputs {uses[o]+=1;}
        let mut values:Vec<Option<Value<'_>>>=(0..self.nodes.len()).map(|_|None).collect();
        for (id,node) in self.nodes.iter().enumerate() {
            let grid=&self.grids[node.grid]; let rows=grid.times.len();
            if grid.observed.len()!=rows*products {return Err(error("grid observation shape mismatch"));}
            let args:Vec<&Value<'_>>=node.children.iter().map(|&c|values[c].as_ref().unwrap()).collect();
            let width=args.iter().map(|v|v.width).max().unwrap_or(products).max(1);
            let owned=|v,w|Value{data:Data::Panel(Cow::Owned(v)),rows,width:w};
            let p=&node.params;
            let input=|index:usize|inputs.get(index).copied().ok_or_else(||error("input column out of range"));
            let value=match node.op.as_str() {
                "column"=> {let data=input(p[0] as usize)?;if data.len()!=rows*products{return Err(error("column matrix shape mismatch"));}Value{data:Data::Panel(Cow::Borrowed(data)),rows,width:products}},
                "const"=>Value{data:Data::Scalar(p[0]),rows,width:0},
                "product"=>{if p.len()!=products{return Err(error("product constant shape mismatch"));}Value{data:Data::Product(p.clone()),rows,width:products}},
                "bar_count"=> {
                    let mut out = vec![f64::NAN; rows * products];
                    for product in 0..products {
                        let mut count = 0_u64;
                        for (row, &timestamp) in grid.times.iter().enumerate() {
                            let offset = product * rows + row;
                            if grid.observed[offset] != 0 {
                                count += u64::from(timestamp >= node.indices[0] && timestamp <= node.indices[1]);
                                out[offset] = count as f64;
                            }
                        }
                    }
                    owned(out, products)
                },
                "reindex"=> {
                    if node.indices.len()!=rows || node.indices.iter().any(|&i|i>=args[0].rows as i64){return Err(error("invalid reindex mapping"));}
                    if let Data::Scalar(v)=args[0].data {Value{data:Data::Scalar(v),rows,width:0}} else {
                        let mut out=vec![f64::NAN;rows*width];
                        for g in 0..width {for(t,&s)in node.indices.iter().enumerate(){if s>=0{out[g*rows+t]=args[0].at(g,s as usize);}}}owned(out,width)
                    }
                },
                "term"=> {
                    let raw=input(node.indices[0] as usize)?;let days=input(node.indices[1] as usize)?;
                    let lengths=input(node.indices[2] as usize)?;let mapping=input(node.indices[3] as usize)?;
                    let slots=node.indices[4] as usize;
                    if slots==0||raw.len()!=lengths.len()*slots||days.len()!=raw.len()||mapping.len()!=rows*products{return Err(error("invalid term curve shape"));}
                    let mut curves=vec![f64::NAN;raw.len()];let ctx=crate::algo::Context::default();
                    let result=if p[3]<7.0 {crate::algo::ta_ft_curve_pair(&ctx,&mut curves,raw,days,lengths,p[0]as usize,p[1]as usize,p[3]as usize)}
                        else {crate::algo::ta_ft_curve_fit(&ctx,&mut curves,raw,days,lengths,p[2]as usize,(p[3]-7.0)as usize)};
                    result.map_err(|e|error(e.to_string()))?;
                    let mut out=vec![f64::NAN;mapping.len()];for(i,&m)in mapping.iter().enumerate(){if m>=0.0{let j=m as usize;if j>=lengths.len(){return Err(error("curve mapping out of range"));}out[i]=curves[j*slots];}}owned(out,products)
                },
                op if op.starts_with("cross:")=>self.cross(&op[6..],&args,node,products,rows)?,
                "since"|"distance"=>self.search(&args,node,grid,products,rows)?,
                op if op.starts_with("rolling:")||op.starts_with("scope:")=>self.temporal(&args,node,grid,products,rows)?,
                op if op.starts_with("session_rolling:")=>self.session_rolling(&op[16..],&args,node,grid,products,rows)?,
                "shift"=> {let mut out=vec![f64::NAN;rows*width];let n=p[0]as usize;for g in 0..width {let observed:Vec<usize>=(0..rows).filter(|&r|width!=products||grid.observed[g*rows+r]!=0).collect();for i in n..observed.len(){out[g*rows+observed[i]]=args[0].at(g,observed[i-n]);}}owned(out,width)},
                "where"=> {let mut out=vec![0.0;rows*width];for g in 0..width {for t in 0..rows{out[g*rows+t]=if args[0].at(g,t)!=0.0{args[1].at(g,t)}else{args[2].at(g,t)};}}owned(out,width)},
                op=> {let mut out=vec![0.0;rows*width];for g in 0..width{for t in 0..rows{out[g*rows+t]=if args.len()==1{unary(op,args[0].at(g,t))}else{binary(op,args[0].at(g,t),args[1].at(g,t))};}}owned(out,width)},
            };
            values[id]=Some(value);
            for &c in &node.children{uses[c]-=1;if uses[c]==0{values[c]=None;}}
            if uses[id]==0{values[id]=None;}
        }
        let mut out=Vec::with_capacity(outputs.len());
        for &id in outputs {uses[id]-=1;if uses[id]==0{out.push(values[id].take().unwrap().output(products));}else{
            let v=values[id].as_ref().unwrap();let width=if v.width==0{products}else{v.width};out.push((0..width).flat_map(|g|(0..v.rows).map(move|t|v.at(g,t))).collect());}}
        Ok(out)
    }

    fn temporal(&self,args:&[&Value<'_>],node:&Node,grid:&Grid,products:usize,rows:usize)->Result<Value<'static>> {
        let p=&node.params;let scope=node.op.starts_with("scope:");let op=node.op.split_once(':').unwrap().1;
        let width=args[0].width.max(1);let mut out=vec![f64::NAN;rows*width];
        out.par_chunks_mut(rows.max(1)).enumerate().try_for_each(|(g,chunk)|->Result<()>{
            let observed:Vec<usize>=(0..rows).filter(|&t|width!=products||grid.observed[g*rows+t]!=0).collect();
            let x:Vec<f64>=observed.iter().map(|&t|args[0].at(g,t)).collect();
            if !scope && args.len()==1 && p[6]<0.0 && p[7]<0.0 {
                if op == "ema" {
                    let mut state = crate::algo::EmaState::new(p[1] as usize)
                        .map_err(|e| error(e.to_string()))?
                        .with_semantics(p[3] as usize, p[4] != 0.0);
                    for (&t, value) in observed.iter().zip(x.iter()) { chunk[t] = state.update(*value); }
                    return Ok(());
                }
                if op.starts_with("linreg_") {
                    let values = panel_linreg(&x, p[1] as usize, op, p[3] as usize, p[4] != 0.0);
                    for (&t, value) in observed.iter().zip(values.iter()) { chunk[t] = *value; }
                    return Ok(());
                }
            }
            let mut base=0;let mut state=if args.len()==1 {Some(crate::algo::IntervalKernel::new(session_op(op,p[5])?).map_err(|e|error(e.to_string()))?.with_semantics(p[3]as usize,p[4]!=0.0))}else{None};
            let mut pair=crate::algo::PairIntervalState::new(op=="corr")
                .with_semantics(p[3] as usize, p[4] != 0.0);
            for (ordinal,&t) in observed.iter().enumerate(){
                if scope && boundary(p[0]as usize,p[1]as usize,p[2]as i64,ordinal,t,base,&observed,grid){
                    base=ordinal;
                    if let Some(state)=state.as_mut(){state.reset_at(ordinal as u64);}
                    else {pair.reset_at(ordinal as u64);}
                }
                let start=if scope {base} else {ordinal.saturating_sub(p[1]as usize-1)};
                let start=start+if p[6]>=0.0{p[6]as usize}else{0};
                let end=if p[7]>=0.0 {(if scope{base}else{ordinal.saturating_sub(p[1]as usize-1)})+p[7]as usize}else{ordinal};
                if start>end {
                    if let Some(state)=state.as_mut(){state.update_explicit(start as u64,end as u64,f64::NAN);}
                    else {pair.update(start as u64,end as u64,f64::NAN,f64::NAN);}
                    chunk[t]=f64::NAN;continue;
                }
                chunk[t]=if let Some(state)=state.as_mut(){state.update_explicit(start as u64,end.min(ordinal)as u64,x[ordinal])}
                    else {pair.update(start as u64,end.min(ordinal)as u64,x[ordinal],args[1].at(g,t))};
            }Ok(())
        })?;Ok(Value{data:Data::Panel(Cow::Owned(out)),rows,width})
    }
    fn session_rolling(&self,op:&str,args:&[&Value<'_>],node:&Node,grid:&Grid,products:usize,rows:usize)->Result<Value<'static>> {
        let p=&node.params;let width=args[0].width.max(1);let mut out=vec![f64::NAN;rows*width];
        let lookback=p[0] as usize;let min=p[1] as usize;let prop=p[2]!=0.0;
        let count=node.indices[0] as usize;
        if count==0 || node.indices.len()!=1+count*3 {return Err(error("invalid session rolling sessions"));}
        let sessions:Vec<(i64,i64,usize)>=node.indices[1..].chunks_exact(3)
            .map(|item|(item[0],item[1],item[2] as usize)).collect();
        crate::algo::factor_plan::SessionWindow::new(&sessions, lookback)?;
        let kernel_op=session_op(op,p[3])?;
        out.par_chunks_mut(rows.max(1)).enumerate().try_for_each(|(g,chunk)|->Result<()>{
            let mut state=crate::algo::IntervalKernel::new_explicit(kernel_op)?.with_semantics(min,prop);
            let mut window = crate::algo::factor_plan::SessionWindow::new(&sessions, lookback)?;
            let mut ordinal = 0;
            for t in 0..rows {
                if width == products && grid.observed[g * rows + t] == 0 { continue; }
                let start = window.start(grid.times[t], ordinal, &sessions)?;
                chunk[t]=state.update_explicit(start,ordinal,args[0].at(g,t));
                ordinal += 1;
            } Ok(())
        })?;Ok(Value{data:Data::Panel(Cow::Owned(out)),rows,width})
    }
    fn search(&self,args:&[&Value<'_>],node:&Node,grid:&Grid,products:usize,rows:usize)->Result<Value<'static>> {
        let p=&node.params;let width=args[0].width.max(1);let distance=node.op=="distance";
        let mut out=vec![f64::NAN;rows*width];
        out.par_chunks_mut(rows.max(1)).enumerate().try_for_each(|(g,chunk)|->Result<()>{
            let observed:Vec<usize>=(0..rows).filter(|&t|width!=products||grid.observed[g*rows+t]!=0).collect();
            let mut base=0;let mut matches=VecDeque::new();let mut registers=vec![0.0;(p.len().saturating_sub(8))/5];
            for (ordinal,&t) in observed.iter().enumerate(){
                if boundary(p[0]as usize,p[1]as usize,p[2]as i64,ordinal,t,base,&observed,grid){base=ordinal;matches.clear();}
                let fallback=if p[5]!=0.0{(ordinal-base)as f64}else{p[6]};
                if !distance {
                    let truth=args[0].at(g,t).is_finite()&&args[0].at(g,t)!=0.0;
                    if truth&&p[3]!=0.0{matches.push_back(ordinal);}
                    let hit=if p[4]!=0.0{matches.back()}else{matches.front()};
                    chunk[t]=hit.map_or(fallback,|&h|(ordinal-h)as f64);
                    if truth&&p[3]==0.0{matches.push_back(ordinal);}
                    if p[7]!=0.0&&args[0].at(g,t).is_nan(){chunk[t]=f64::NAN;}
                } else {
                    chunk[t]=fallback;
                    if !args[0].at(g,t).is_finite(){continue;}
                    let nearest=p[4]!=0.0;
                    for step in 0..ordinal-base {
                        let h=if nearest{ordinal-1-step}else{base+step};let candidate=args[0].at(g,observed[h]);if !candidate.is_finite(){continue;}
                        for(i,instruction)in p[8..].chunks_exact(5).enumerate(){
                            let code=instruction[0]as usize;let a=instruction[1]as usize;let b=instruction[2]as usize;let c=instruction[3]as usize;
                            registers[i]=match code{0=>args[0].at(g,t),1=>candidate,2=>instruction[4],3=>args[a].at(g,t),
                                4=>if registers[a]!=0.0{registers[b]}else{registers[c]},
                                10..=16=>unary(["neg","abs","sign","sqrt","log","tanh","not"][code-10],registers[a]),
                                20..=36=>binary(["add","sub","mul","div","pow","max","min","gt","lt","ge","le","eq","ne","and","or","max","min"][code-20],registers[a],registers[b]),
                                _=>return Err(error("invalid match predicate opcode"))};
                        }
                        if registers.last().is_some_and(|v|v.is_finite()&&*v!=0.0){chunk[t]=(ordinal-h)as f64;break;}
                    }
                }
            }Ok(())
        })?;Ok(Value{data:Data::Panel(Cow::Owned(out)),rows,width})
    }
    fn cross(&self,op:&str,args:&[&Value<'_>],node:&Node,products:usize,rows:usize)->Result<Value<'static>> {
        let correlation=op=="corr"||op=="spearman";let width=if correlation{1}else{products};
        let mut row_major=vec![f64::NAN;rows*width];
        let priorities:Vec<i64>=if node.indices.len()==products{node.indices.clone()}else{(0..products as i64).collect()};
        row_major.par_chunks_mut(width).enumerate().for_each(|(t,row)|{
            let masked=matches!(op,"rank_masked"|"ordinal_rank_asc"|"ordinal_rank_desc"|"group_rank"|"group_zscore"|"group_demean"|"residualize");
            let mask=if op=="residualize"{args.len()-1}else{1};
            let valid:Vec<(usize,f64)>=(0..products).filter_map(|g|{let v=args[0].at(g,t);(!v.is_nan()&&(!masked||{let m=args[mask].at(g,t);!m.is_nan()&&m!=0.0})).then_some((g,v))}).collect();
            if correlation {
                let pairs:Vec<(usize,f64)>=valid.into_iter().filter(|(g,_)|!args[1].at(*g,t).is_nan()).collect();
                if pairs.len()<2{return;}
                let mut x:Vec<f64>=pairs.iter().map(|(_,v)|*v).collect();let mut y:Vec<f64>=pairs.iter().map(|(g,_)|args[1].at(*g,t)).collect();
                if op=="spearman"{let xr=ranks(&pairs,false,false,&priorities);let yr=ranks(&pairs.iter().map(|(g,_)|(*g,args[1].at(*g,t))).collect::<Vec<_>>(),false,false,&priorities);for(i,(g,_))in pairs.iter().enumerate(){x[i]=xr.iter().find(|(j,_)|j==g).unwrap().1;y[i]=yr.iter().find(|(j,_)|j==g).unwrap().1;}}
                let n=x.len()as f64;let mx=x.iter().sum::<f64>()/n;let my=y.iter().sum::<f64>()/n;
                let(mut xx,mut yy,mut xy)=(0.0,0.0,0.0);for(x,y)in x.iter().zip(y){xx+=(x-mx).powi(2);yy+=(y-my).powi(2);xy+=(x-mx)*(y-my);}if xx>0.0&&yy>0.0{row[0]=xy/(xx*yy).sqrt();}return;
            }
            if op=="residualize" {
                let k=args.len()-2;let eligible:Vec<(usize,f64)>=valid.into_iter().filter(|(g,v)|v.is_finite()&&(1..=k).all(|a|args[a].at(*g,t).is_finite())).collect();
                let n=eligible.len();if n<=k+1{return;}
                // Reorthogonalized pivoted QR projects onto the design's column
                // space, including rank-deficient/collinear exposures.
                let mut residual:Vec<f64>=eligible.iter().map(|(_,v)|*v).collect();
                let mut design:Vec<Vec<f64>>=(0..=k).map(|a|eligible.iter().map(|(g,_)|if a==0{1.0}else{args[a].at(*g,t)}).collect()).collect();
                let norm=|v:&Vec<f64>|v.iter().map(|x|x*x).sum::<f64>().sqrt();
                let scale=design.iter().map(norm).fold(0.0,f64::max);let tolerance=f64::EPSILON*(n.max(k+1)as f64)*scale;
                for a in 0..=k {let pivot=(a..=k).max_by(|&i,&j|norm(&design[i]).total_cmp(&norm(&design[j]))).unwrap();design.swap(a,pivot);let length=norm(&design[a]);if length<=tolerance{break;}let q:Vec<f64>=design[a].iter().map(|x|x/length).collect();for _ in 0..2{let dot=residual.iter().zip(&q).map(|(x,y)|x*y).sum::<f64>();for(i,x)in residual.iter_mut().enumerate(){*x-=dot*q[i];}for column in design.iter_mut().skip(a+1){let dot=column.iter().zip(&q).map(|(x,y)|x*y).sum::<f64>();for(i,x)in column.iter_mut().enumerate(){*x-=dot*q[i];}}}}
                for((g,_),v)in eligible.iter().zip(residual){row[*g]=v;}return;
            }
            let groups:Vec<i64>=if op.starts_with("group_"){let mut labels=node.params.iter().map(|v|*v as i64).filter(|&v|v>=0).collect::<Vec<_>>();labels.sort_unstable();labels.dedup();labels}else{vec![0]};
            for label in groups {
                let members:Vec<(usize,f64)>=valid.iter().copied().filter(|(g,_)|!op.starts_with("group_")||node.params[*g]as i64==label).collect();if members.is_empty(){continue;}
                if op.contains("rank") {
                    let ordinal=op.starts_with("ordinal");let n=members.len()as f64;
                    for(g,v)in ranks(&members,ordinal,op.ends_with("desc"),&priorities){row[g]=if ordinal{v}else{v/n-0.5};}
                }else{
                    let n=members.len()as f64;let mean=members.iter().map(|(_,v)|v).sum::<f64>()/n;
                    let std=(members.iter().map(|(_,v)|(v-mean).powi(2)).sum::<f64>()/(n-1.0)).sqrt();
                    for(g,v)in members{row[g]=if op.ends_with("demean"){v-mean}else if n<2.0||std.is_nan(){f64::NAN}else if std==0.0{0.0}else{(v-mean)/std};}
                }
            }
        });
        let mut output=vec![f64::NAN;rows*width];for t in 0..rows{for g in 0..width{output[g*rows+t]=row_major[t*width+g];}}
        Ok(Value{data:Data::Panel(Cow::Owned(output)),rows,width})
    }
}
fn boundary(kind:usize,count:usize,gap:i64,ordinal:usize,t:usize,base:usize,observed:&[usize],grid:&Grid)->bool {
    ordinal==0||match kind{1=>ordinal-base>=count.max(1),2=>grid.days[t]!=grid.days[observed[ordinal-1]],3=>grid.times[t]-grid.times[observed[ordinal-1]]>=gap,_=>false}
}

#[cfg(test)]
mod audit_tests {
    use super::*;

    #[test]
    fn partition_switch_does_not_carry_truncated_state() {
        let mut plan = PanelPlan::new();
        let grid = plan.grid(&[0, 1, 2, 3, 4, 5], &[0, 0, 0, 0, 0, 0], &[1; 6]).unwrap();
        let column = plan.add("column".into(), vec![], vec![0.0], vec![], grid).unwrap();
        let scoped = plan.add(
            "scope:mean".into(), vec![column],
            vec![1.0, 2.0, 0.0, 1.0, 0.0, 0.5, 1.0, -1.0], vec![], grid,
        ).unwrap();
        let values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0];
        let out = plan.execute(&[&values], &[scoped], 1).unwrap();
        assert!(out[0][2].is_nan(), "new partition must not reuse the previous partition result");
        assert_eq!(out[0][3], 4.0);
    }
}


fn panel_linreg(values: &[f64], window: usize, metric: &str, min: usize, prop: bool) -> Vec<f64> {
    let window = window.max(1);
    let mut out = vec![f64::NAN; values.len()];
    let (mut sx, mut sy, mut sxx, mut syy, mut sxy) = (0.0, 0.0, 0.0, 0.0, 0.0);
    let mut count = 0usize;
    for index in 0..values.len() {
        let x = index as f64;
        let y = values[index];
        if y.is_finite() { sx += x; sy += y; sxx += x * x; syy += y * y; sxy += x * y; count += 1; }
        if index >= window {
            let old_x = (index - window) as f64;
            let old_y = values[index - window];
            if old_y.is_finite() { sx -= old_x; sy -= old_y; sxx -= old_x * old_x; syy -= old_y * old_y; sxy -= old_x * old_y; count -= 1; }
        }
        let width = (index + 1).min(window);
        if count < min.max(3) || (prop && count < width) { continue; }
        let n = count as f64;
        let cxx = sxx - sx * sx / n;
        if cxx <= 0.0 { continue; }
        let cyy = syy - sy * sy / n;
        let cxy = sxy - sx * sy / n;
        let slope = cxy / cxx;
        let intercept = (sy - slope * sx) / n;
        let sse = (syy - intercept * sy - slope * sxy).max(0.0);
        out[index] = match metric {
            "linreg_slope" => slope,
            "linreg_r2" => if cyy <= 0.0 { f64::NAN } else { 1.0 - sse / cyy },
            "linreg_resid_std" => if count < 3 { f64::NAN } else { (sse / (n - 2.0)).sqrt() },
            "linreg_tstat" => {
                if count < 3 { f64::NAN } else {
                    let se = ((sse / (n - 2.0)) / cxx).sqrt();
                    if se > 0.0 { slope / se } else { f64::NAN }
                }
            }
            _ => f64::NAN,
        };
    }
    out
}

#[cfg(test)]
mod session_rolling_tests {
    use super::*;

    #[test]
    fn batch_session_rolling_uses_observations_not_calendar_capacity() {
        let mut plan = PanelPlan::new();
        let grid = plan.grid(&[0, 1, 2, 3, 4], &[0, 0, 0, 0, 0], &[1; 5]).unwrap();
        let column = plan.add("column".into(), vec![], vec![0.0], vec![], grid).unwrap();
        let node = plan.add(
            "session_rolling:mean".into(), vec![column], vec![1.0, 1.0, 0.0, 0.5],
            vec![2, 0, 2, 2, 3, 5, 3], grid,
        ).unwrap();
        let values = [1.0, 3.0, 10.0, 20.0, 30.0];
        let out = plan.execute(&[&values], &[node], 1).unwrap();
        assert!((out[0][2] - 14.0 / 3.0).abs() < 1e-9);
        assert_eq!(out[0][3], 20.0);
        assert_eq!(out[0][4], 25.0);
    }

    #[test]
    fn product_lanes_cross_barrier_and_downstream_lanes_match_streaming() {
        let (products, rows) = (4, 128);
        let mut plan = PanelPlan::new();
        let grid = plan.grid(&(0..rows as i64).collect::<Vec<_>>(), &vec![0; rows], &vec![1; rows * products]).unwrap();
        let column = plan.add("column".into(), vec![], vec![0.0], vec![], grid).unwrap();
        let mean = plan.add("rolling:mean".into(), vec![column], vec![1.0, 8.0, 0.0, 1.0, 0.0, 0.5, -1.0, -1.0], vec![], grid).unwrap();
        let cross = plan.add("cross:zscore".into(), vec![mean], vec![], vec![], grid).unwrap();
        let output = plan.add("rolling:mean".into(), vec![cross], vec![1.0, 4.0, 0.0, 1.0, 0.0, 0.5, -1.0, -1.0], vec![], grid).unwrap();
        let input: Vec<f64> = (0..products).flat_map(|g| (0..rows).map(move |t| ((t * (g + 1)) as f64).sin() + g as f64)).collect();
        let serial = rayon::ThreadPoolBuilder::new().num_threads(1).build().unwrap()
            .install(|| plan.execute_panel(&[&input], &[output], products).unwrap());
        let parallel = rayon::ThreadPoolBuilder::new().num_threads(4).build().unwrap()
            .install(|| plan.execute_panel(&[&input], &[output], products).unwrap());
        assert_eq!(serial, parallel);
        let json = r#"{"nodes":[{"kind":"column","index":0},
          {"kind":"rolling","child":0,"window":8,"op":"mean","min_periods":1,"propagate_nan":false},
          {"kind":"cross","child":1,"op":"zscore"},
          {"kind":"rolling","child":2,"window":4,"op":"mean","min_periods":1,"propagate_nan":false}],"outputs":[3]}"#;
        let mut kernel = crate::algo::FactorPlanKernel::from_spec_json(json, products).unwrap();
        for row in 0..rows {
            let values: Vec<f64> = (0..products).map(|g| input[g * rows + row]).collect();
            let actual = kernel.update_at(row as i64, &values).unwrap();
            for product in 0..products {
                assert!((actual[product] - serial[0][product * rows + row]).abs() < 1e-10);
            }
        }
    }
}

#[cfg(test)]
mod grid_dedup_tests {
    use super::*;

    #[test]
    fn identical_grids_share_one_allocation() {
        let mut plan = PanelPlan::new();
        let first = plan.grid(&[1, 2], &[0, 0], &[1, 1]).unwrap();
        let second = plan.grid(&[1, 2], &[0, 0], &[1, 1]).unwrap();
        assert_eq!(first, second);
        let different = plan.grid(&[1, 3], &[0, 0], &[1, 1]).unwrap();
        assert_ne!(first, different);
    }
}
