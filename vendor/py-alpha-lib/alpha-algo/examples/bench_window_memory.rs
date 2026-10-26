//! Fixed-window lifetime test; unique observations force insert/evict cycles.
use alpha_algo::{IntervalKernel, SessionOp};
use std::{hint::black_box, time::Instant};

fn main() {
    let name = std::env::args().nth(1).unwrap_or_else(|| "quantile".into());
    let op = match name.as_str() {
        "quantile" => SessionOp::Quantile(0.5), "rank" => SessionOp::Rank,
        "mad" => SessionOp::Mad, _ => panic!("expected quantile, rank or mad"),
    };
    for sample in 0..5 {
        let mut kernel = IntervalKernel::new_explicit(op).unwrap();
        let start = Instant::now();
        for index in 0_u64..1_000_000 {
            black_box(kernel.update_explicit(index.saturating_sub(479), index, index as f64));
        }
        println!("op={name} sample={sample} bars=1000000 window=480 elapsed_us={}", start.elapsed().as_micros());
    }
}
