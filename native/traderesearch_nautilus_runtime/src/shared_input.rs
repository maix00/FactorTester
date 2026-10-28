//! Thin shared-buffer adapter. Ordering, merging and engine replay stay Nautilus-owned.
use std::{cell::Cell, rc::Rc};

use nautilus_backtest::{
    node::{merge_streams, stream_chunks},
    python::engine::PyBacktestEngine,
};
use nautilus_core::UnixNanos;
use nautilus_data::replay::ReplayBatch;
use nautilus_model::data::{
    Bar, DataBatch, HasTsInit, InstrumentClose, InstrumentStatus, IntoDataBatch, NautilusDataType,
    QuoteTick, TradeTick,
};
use nautilus_model::python::data::PyNautilusDataType;
use nautilus_persistence::common::datafusion::cast_record_batch_to_schema;
use nautilus_serialization::arrow::{DecodeFromRecordBatch, schema_without_identifier_column};
use pyo3::{
    exceptions::{PyRuntimeError, PyStopIteration},
    prelude::*,
};
use traderesearch_data_io::MappedIpc;

struct SharedStream {
    decoder: Decoder,
    source: Py<PyAny>,
    start: Option<u64>,
    end: Option<u64>,
    previous: Option<u64>,
    count: Rc<Cell<usize>>,
    total: Rc<Cell<usize>>,
    max_events: usize,
    max_batch: usize,
    max_bytes: usize,
    failed: bool,
}

type Decoder = fn(&mut SharedStream, &MappedIpc) -> anyhow::Result<DataBatch>;

impl SharedStream {
    fn decode<T>(&mut self, input: &MappedIpc) -> anyhow::Result<DataBatch>
    where
        T: DecodeFromRecordBatch + IntoDataBatch + HasTsInit,
    {
        anyhow::ensure!(
            input.len() == 1,
            "cache publication must contain exactly one batch"
        );
        let batch = input.batch(0)?;
        anyhow::ensure!(
            batch.num_rows() <= self.max_batch,
            "shared input batch exceeds hard bound"
        );
        let metadata = batch.schema().metadata().clone();
        let schema = schema_without_identifier_column(&T::get_schema(Some(metadata.clone())));
        let batch = cast_record_batch_to_schema(&batch, &schema)?;
        // Native typed decoders use their authoritative schema order. Cache
        // projection ordering must not be interpreted as event field ordering.
        // project() only clones array references, not the underlying values.
        let order = schema
            .fields()
            .iter()
            .map(|field| batch.schema().index_of(field.name()))
            .collect::<Result<Vec<_>, _>>()?;
        let batch = batch.project(&order)?;
        let mut rows = T::decode_batch(&metadata, batch)?;
        for row in &rows {
            let timestamp = row.ts_init().as_u64();
            anyhow::ensure!(
                self.previous.is_none_or(|previous| previous <= timestamp),
                "shared input must be ordered by ts_init"
            );
            self.previous = Some(timestamp);
        }
        rows.retain(|row| {
            self.start
                .is_none_or(|start| row.ts_init().as_u64() >= start)
                && self.end.is_none_or(|end| row.ts_init().as_u64() <= end)
        });
        let count = self
            .count
            .get()
            .checked_add(rows.len())
            .ok_or_else(|| anyhow::anyhow!("shared input count overflow"))?;
        let total = self
            .total
            .get()
            .checked_add(rows.len())
            .ok_or_else(|| anyhow::anyhow!("combined shared input count overflow"))?;
        anyhow::ensure!(
            total <= self.max_events,
            "shared input event budget exceeded"
        );
        self.total.set(total);
        self.count.set(count);
        Ok(T::into_batch(rows))
    }

    fn next_input(&mut self) -> anyhow::Result<Option<ReplayBatch>> {
        loop {
            let input = Python::attach(|py| -> PyResult<Option<MappedIpc>> {
                let file = match self.source.bind(py).call_method0("__next__") {
                    Ok(file) => file,
                    Err(error) if error.is_instance_of::<PyStopIteration>(py) => return Ok(None),
                    Err(error) => return Err(error),
                };
                #[cfg(unix)]
                {
                    use std::os::fd::BorrowedFd;
                    let fd = file.call_method0("fileno")?.extract::<i32>()?;
                    if fd < 0 {
                        return Err(PyRuntimeError::new_err("invalid input fd"));
                    }
                    // SAFETY: Python retains the open file while its fd is duplicated.
                    let owned = unsafe { BorrowedFd::borrow_raw(fd) }.try_clone_to_owned()?;
                    let file: std::fs::File = owned.into();
                    if file.metadata()?.len() > self.max_bytes as u64 {
                        return Err(PyRuntimeError::new_err("shared input byte budget exceeded"));
                    }
                    // SAFETY: source supplies immutable cache publications only.
                    // Decimal128 buffers from 8-byte-aligned IPC producers may
                    // need a bounded alignment copy before native event decode.
                    unsafe { MappedIpc::from_file_with_alignment_copy(file) }
                        .map(Some)
                        .map_err(|e| PyRuntimeError::new_err(e.to_string()))
                }
                #[cfg(not(unix))]
                {
                    Err(PyRuntimeError::new_err(
                        "shared input handle transfer is not supported on this host",
                    ))
                }
            })?;
            let Some(input) = input else {
                return Ok(None);
            };
            let batch = (self.decoder)(self, &input)?;
            if !batch.is_empty() {
                return Ok(Some(ReplayBatch::Typed(batch)));
            }
        }
    }
}

impl Iterator for SharedStream {
    type Item = anyhow::Result<ReplayBatch>;
    fn next(&mut self) -> Option<Self::Item> {
        if self.failed {
            return None;
        }
        match self.next_input() {
            Ok(batch) => batch.map(Ok),
            Err(error) => {
                self.failed = true;
                Some(Err(error))
            }
        }
    }
}

#[pyfunction]
#[pyo3(signature=(engine, sources, chunk_size, max_chunk_events, max_input_events, max_input_batch_bytes=134217728, start=None, end=None))]
pub fn replay_shared_inputs(
    py: Python<'_>,
    mut engine: PyRefMut<'_, PyBacktestEngine>,
    sources: Vec<(Py<PyNautilusDataType>, Py<PyAny>)>,
    chunk_size: usize,
    max_chunk_events: usize,
    max_input_events: usize,
    max_input_batch_bytes: usize,
    start: Option<u64>,
    end: Option<u64>,
) -> PyResult<(usize, usize, usize, Vec<usize>)> {
    let sources: Vec<_> = sources
        .into_iter()
        .map(|(kind, source)| (kind.borrow(py).inner(), source))
        .collect();
    let run = || -> anyhow::Result<_> {
        anyhow::ensure!(
            engine.inner().run_started().is_none(),
            "reset engine before shared replay"
        );
        anyhow::ensure!(!sources.is_empty(), "shared replay requires sources");
        anyhow::ensure!(max_input_events > 0, "positive input event budget required");
        anyhow::ensure!(
            max_input_batch_bytes > 0,
            "positive input byte budget required"
        );
        anyhow::ensure!(
            (1..=1_000_000).contains(&chunk_size) && max_chunk_events >= chunk_size,
            "invalid shared replay chunk bounds"
        );
        anyhow::ensure!(
            !matches!((start,end), (Some(first),Some(last)) if first > last),
            "replay start must not follow end"
        );
        let decoders = sources
            .iter()
            .map(|(kind, _)| -> anyhow::Result<Decoder> {
                Ok(match kind {
                    NautilusDataType::Bar => SharedStream::decode::<Bar>,
                    NautilusDataType::QuoteTick => SharedStream::decode::<QuoteTick>,
                    NautilusDataType::TradeTick => SharedStream::decode::<TradeTick>,
                    NautilusDataType::InstrumentClose => SharedStream::decode::<InstrumentClose>,
                    NautilusDataType::InstrumentStatus => SharedStream::decode::<InstrumentStatus>,
                    other => anyhow::bail!("unsupported shared input event type {other:?}"),
                })
            })
            .collect::<anyhow::Result<Vec<_>>>()?;
        let counts: Vec<_> = sources.iter().map(|_| Rc::new(Cell::new(0))).collect();
        let total = Rc::new(Cell::new(0));
        let streams = sources
            .into_iter()
            .enumerate()
            .map(|(index, (kind, source))| {
                (
                    format!("shared {index} ({kind})"),
                    SharedStream {
                        decoder: decoders[index],
                        source,
                        start,
                        end,
                        previous: None,
                        count: counts[index].clone(),
                        total: total.clone(),
                        max_events: max_input_events,
                        max_batch: max_chunk_events,
                        max_bytes: max_input_batch_bytes,
                        failed: false,
                    },
                )
            })
            .collect();
        let merged = merge_streams(streams)?;
        let stats = stream_chunks(
            engine.inner_mut(),
            start.map(UnixNanos::from),
            end.map(UnixNanos::from),
            "shared-input-replay",
            merged.peekable(),
            chunk_size,
            Some(max_chunk_events),
        )?;
        let source_counts: Vec<usize> = counts.iter().map(|count| count.get()).collect();
        anyhow::ensure!(
            source_counts.iter().sum::<usize>() <= max_input_events,
            "combined shared input event budget exceeded"
        );
        Ok((
            stats.events,
            stats.chunks,
            stats.max_chunk_events,
            source_counts,
        ))
    };
    run().map_err(|error| PyRuntimeError::new_err(format!("{error:#}")))
}
