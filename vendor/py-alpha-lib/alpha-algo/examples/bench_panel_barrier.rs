//! Same DAG and data, serial or product-parallel via RAYON_NUM_THREADS.
//! Graph: rolling mean(480) -> cross-sectional zscore -> rolling mean(20).
use alpha_algo::PanelPlan;
use std::{hint::black_box, time::Instant};

fn main() {
    let products = 8;
    let rows = 100_000;
    let times: Vec<i64> = (0..rows as i64).collect();
    let observed = vec![1; rows * products];
    let input: Vec<f64> = (0..products).flat_map(|product| (0..rows).map(move |row|
        ((row * (product + 1)) as f64 / 100.0).sin() + product as f64
    )).collect();
    let mut plan = PanelPlan::new();
    let grid = plan.grid(&times, &vec![0; rows], &observed).unwrap();
    let column = plan.add("column".into(), vec![], vec![0.0], vec![], grid).unwrap();
    let mean = plan.add("rolling:mean".into(), vec![column], vec![1.0, 480.0, 0.0, 1.0, 0.0, 0.5, -1.0, -1.0], vec![], grid).unwrap();
    let cross = plan.add("cross:zscore".into(), vec![mean], vec![], vec![], grid).unwrap();
    let output = plan.add("rolling:mean".into(), vec![cross], vec![1.0, 20.0, 0.0, 1.0, 0.0, 0.5, -1.0, -1.0], vec![], grid).unwrap();
    black_box(plan.execute_panel(&[&input], &[output], products).unwrap());
    for sample in 0..5 {
        let start = Instant::now();
        let result = plan.execute_panel(&[&input], &[output], products).unwrap();
        let elapsed = start.elapsed().as_micros();
        let checksum: f64 = result[0].iter().map(|value| value * value).sum();
        println!("sample={sample} rows={rows} products={products} elapsed_us={elapsed} checksum={checksum:.12}");
        black_box(result);
    }
}
