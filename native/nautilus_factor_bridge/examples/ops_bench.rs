use std::time::Instant;

use nautilus_factor_bridge::{FactorEngine, MarketBar};

fn run(name: &str, json: &str, products: usize, n: usize) {
    let mut samples = Vec::new();
    for _ in 0..3 {
        let mut engine = nautilus_factor_bridge::FactorPlanEngine::from_spec_json(json, products).unwrap();
        let mut out = Vec::new();
        let mut bar = MarketBar::new(0, vec![String::new(); products], vec![0.0; products]);
        let started = Instant::now();
        let mut sink = 0.0;
        for index in 0..n {
            bar.timestamp_ns = index as i64;
            for product in 0..products {
                bar.values[product] = (index as f64 + product as f64).sin();
            }
            engine.update_into(&bar, &mut out).unwrap();
            sink += out[0];
        }
        samples.push(started.elapsed().as_secs_f64());
        std::hint::black_box(sink);
    }
    samples.sort_by(f64::total_cmp);
    println!("{name}={:.6}s", samples[1]);
}

fn main() {
    let n = 1_000_000;
    run("rolling_mean", r#"{"columns":["C"],"nodes":[{"kind":"column","index":0},{"kind":"rolling","child":0,"window":480,"op":"mean","min_periods":1,"propagate_nan":true}],"outputs":[1]}"#, 1, n);
    run("ema", r#"{"columns":["C"],"nodes":[{"kind":"column","index":0},{"kind":"rolling","child":0,"window":480,"op":"ema","min_periods":1,"propagate_nan":true}],"outputs":[1]}"#, 1, n);
    run("linreg_slope", r#"{"columns":["C"],"nodes":[{"kind":"column","index":0},{"kind":"rolling","child":0,"window":480,"op":"linreg_slope","min_periods":3,"propagate_nan":true}],"outputs":[1]}"#, 1, n);
    run("since", r#"{"columns":["C"],"nodes":[{"kind":"column","index":0},{"kind":"since","condition":0,"count":3,"include_current":true,"nearest":true,"default_scope":true,"default":0.0}],"outputs":[1]}"#, 1, n);
    run("argmin_raw", r#"{"columns":["C"],"nodes":[{"kind":"column","index":0},{"kind":"rolling","child":0,"window":480,"op":"argmin_raw","min_periods":1,"propagate_nan":true}],"outputs":[1]}"#, 1, n);
    run("quantile", r#"{"columns":["C"],"nodes":[{"kind":"column","index":0},{"kind":"rolling","child":0,"window":480,"op":"quantile","quantile":0.5,"min_periods":1,"propagate_nan":true}],"outputs":[1]}"#, 1, n);
    run("cross_rank", r#"{"columns":["C"],"nodes":[{"kind":"column","index":0},{"kind":"cross","child":0,"op":"rank"}],"outputs":[1]}"#, 4, n);
}
