//! Validate an existing Python-published immutable IPC file from Rust.
use traderesearch_data_io::MappedIpc;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = std::env::args_os()
        .nth(1)
        .ok_or("IPC path or --fd required")?;
    // SAFETY: this diagnostic is for immutable cache publications only; callers
    // must not pass files being rewritten in place.
    #[cfg(unix)]
    let reader = if path == "--fd" {
        use std::os::fd::FromRawFd;
        let fd: i32 = std::env::args()
            .nth(2)
            .ok_or("inherited fd required")?
            .parse()?;
        if fd < 3 {
            return Err("expected explicitly inherited data fd".into());
        }
        // SAFETY: diagnostic caller explicitly transfers ownership of this fd.
        let file = unsafe { std::fs::File::from_raw_fd(fd) };
        unsafe { MappedIpc::from_file(file) }?
    } else {
        unsafe { MappedIpc::open(path) }?
    };
    #[cfg(not(unix))]
    let reader = unsafe { MappedIpc::open(path) }?;
    let mut rows = 0;
    for index in 0..reader.len() {
        rows += reader.batch(index)?.num_rows();
    }
    println!("batches={} rows={rows}", reader.len());
    Ok(())
}
