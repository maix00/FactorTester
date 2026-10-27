//! Borrowed JSONL output shared by replay tools and runtime diagnostics.
use crate::{FactorOutputSink, FactorUpdate};
use anyhow::Context;
use serde::Serialize;
use std::{
    fs::File,
    io::{BufWriter, Write},
};

pub struct JsonFactorSink {
    output: BufWriter<File>,
    rows: u64,
    expected: Option<u64>,
}

#[derive(Serialize)]
struct Row<'a> {
    timestamp_ns: i64,
    available_at_ns: i64,
    values: &'a [f64],
}

impl JsonFactorSink {
    pub fn new(file: File, expected: Option<u64>) -> Self {
        Self {
            output: BufWriter::with_capacity(65_536, file),
            rows: 0,
            expected,
        }
    }
}

impl FactorOutputSink for JsonFactorSink {
    fn write_update(&mut self, update: &FactorUpdate) -> anyhow::Result<()> {
        serde_json::to_writer(
            &mut self.output,
            &Row {
                timestamp_ns: update.timestamp_ns,
                available_at_ns: update.available_at_ns,
                values: &update.values,
            },
        )?;
        self.output.write_all(b"\n")?;
        self.rows += 1;
        Ok(())
    }
    fn finish(&mut self) -> anyhow::Result<()> {
        anyhow::ensure!(
            self.expected.is_none_or(|expected| self.rows == expected),
            "factor output count {} differs from frozen expected {}",
            self.rows,
            self.expected.unwrap_or(self.rows)
        );
        self.output.flush().context("flush factor output")
    }
}
