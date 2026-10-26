use std::time::Instant;

use nautilus_factor_bridge::{FactorEngine, MarketBar};

fn main() {
    let json = r#"{
      "columns":["CLOSE"],
      "nodes":[
        {"kind":"column","index":0},
        {"kind":"rolling","child":0,"window":480,"op":"mean","min_periods":1,"propagate_nan":true}
      ],
      "outputs":[1]
    }"#;
    let n = 1_000_000usize;
    let mut samples = Vec::new();
    for _ in 0..5 {
        let mut engine = nautilus_factor_bridge::FactorPlanEngine::from_spec_json(json, 1).unwrap();
        let started = Instant::now();
        let mut sink = 0.0;
        let mut out = Vec::new();
        for index in 0..n {
            let bar = MarketBar::new(index as i64, vec!["A".into()], vec![(index as f64).sin()]);
            engine.update_into(&bar, &mut out).unwrap();
            sink += out[0];
        }
        samples.push(started.elapsed().as_secs_f64());
        std::hint::black_box(sink);
    }
    samples.sort_by(f64::total_cmp);
    println!("bridge_1m_median={:.6}s samples={samples:?}", samples[2]);
}
