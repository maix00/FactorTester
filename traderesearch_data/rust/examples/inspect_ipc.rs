//! Validate an existing Python-published immutable IPC file from Rust.
use traderesearch_data_io::MappedIpc;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = std::env::args_os().nth(1).ok_or("IPC path required")?;
    // SAFETY: this diagnostic is for immutable cache publications only; callers
    // must not pass files being rewritten in place.
    let reader = unsafe { MappedIpc::open(path) }?;
    let mut rows = 0;
    for index in 0..reader.len() {
        rows += reader.batch(index)?.num_rows();
    }
    println!("batches={} rows={rows}", reader.len());
    Ok(())
}
