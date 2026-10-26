//! Isolated release baseline: 200k updates, one product, five warm samples.
use alpha_algo::{ExprSpec, FactorPlanKernel};
use std::{hint::black_box, time::Instant};

fn main() {
    for sample in 0..5 {
        let mut kernel = FactorPlanKernel::new(1, vec![ExprSpec::BarCount {
            start_ns: 0, end_ns: 200_000,
        }], vec![0]).unwrap();
        let mut output = Vec::new();
        let start = Instant::now();
        for timestamp in 0..200_000 {
            kernel.update_into(timestamp, black_box(&[1.0]), &mut output).unwrap();
            black_box(&output);
        }
        println!("sample={sample} updates=200000 elapsed_us={} count={}", start.elapsed().as_micros(), output[0]);
    }
}
