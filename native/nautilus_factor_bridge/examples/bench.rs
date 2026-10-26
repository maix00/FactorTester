use std::time::Instant;

use nautilus_factor_bridge::{FactorEngine, MarketBar};

fn main() {
    let json = r#"{
      "columns":["CLOSE"],
      "nodes":[
        {"kind":"column","index":0},
        {"kind":"rolling","child":0,"window":480,"op":"mean","min_periods":1,"propagate_nan":true},
        {"kind":"const","value":1.0},
        {"kind":"binary","op":"add","left":1,"right":2}
      ],
      "outputs":[1,3]
    }"#;
    let mut engine = nautilus_factor_bridge::FactorPlanEngine::from_spec_json(json, 1).unwrap();
    let n = 1_000_000;
    let start = Instant::now();
    let mut sink = 0.0;
    for index in 0..n {
        let bar = MarketBar::new(index as i64, vec!["A".into()], vec![(index as f64).sin()]);
        sink += engine.update(&bar).unwrap()[0];
    }
    let elapsed = start.elapsed();
    println!("bridge_1m={:.6}s sink={sink}", elapsed.as_secs_f64());
}
