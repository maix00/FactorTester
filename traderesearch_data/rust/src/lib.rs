//! Read the same immutable, uncompressed IPC buffers used by Python Arrow.
//!
//! Cache publication, identity, authorization and quotas belong to the caller;
//! this crate deliberately implements none of those policies a second time.
use std::{fs::File, path::Path, ptr::NonNull, sync::Arc};

use arrow_array::RecordBatch;
use arrow_buffer::Buffer;
use arrow_ipc::{
    convert::fb_to_schema,
    reader::{FileDecoder, read_footer_length},
    root_as_footer,
};
use arrow_schema::ArrowError;
use memmap2::MmapOptions;

fn invalid(message: &str) -> ArrowError {
    ArrowError::ParseError(message.into())
}

/// A batch owns its mapping through Arrow's reference-counted buffer owner.
/// Dropping the reader or unlinking the published file does not invalidate it.
pub struct MappedIpc {
    buffer: Buffer,
    decoder: FileDecoder,
    blocks: Vec<arrow_ipc::Block>,
    data_end: usize,
}

impl MappedIpc {
    /// Map a published cache file without copying its array values.
    ///
    /// # Safety
    /// No process may modify or truncate the underlying inode while any returned
    /// batch is alive. Atomic replacement/unlink is allowed; in-place writes are
    /// not. The cache producer must enforce this immutable publication contract.
    pub unsafe fn open(path: impl AsRef<Path>) -> Result<Self, ArrowError> {
        let file = File::open(path)?;
        // SAFETY: forwarded unchanged from this function's caller.
        unsafe { Self::from_file(file) }
    }

    /// Map an already-open immutable cache file.
    ///
    /// This avoids reopening a path which eviction or atomic replacement may
    /// have changed between cache admission and native consumption. A caller
    /// may pass a duplicated or transferred OS file handle.
    ///
    /// # Safety
    /// The same inode immutability guarantee as [`Self::open`] is required.
    pub unsafe fn from_file(file: File) -> Result<Self, ArrowError> {
        if file.metadata()?.len() < 10 {
            return Err(invalid("IPC file is too short"));
        }
        // SAFETY: the caller guarantees immutable inode contents and length.
        let mapping = Arc::new(unsafe { MmapOptions::new().map(&file)? });
        let ptr = NonNull::new(mapping.as_ptr() as *mut u8)
            .ok_or_else(|| invalid("empty IPC mapping"))?;
        let len = mapping.len();
        // SAFETY: ptr addresses len mapped bytes; Buffer retains the mapping
        // owner even when this reader and the original file handle are dropped.
        let buffer = unsafe { Buffer::from_custom_allocation(ptr, len, mapping) };
        if !buffer.starts_with(b"ARROW1") {
            return Err(invalid("expected Arrow IPC file"));
        }
        let trailer = len - 10;
        let footer_len = read_footer_length(buffer[trailer..].try_into().unwrap())?;
        let start = trailer
            .checked_sub(footer_len)
            .filter(|start| *start >= 8)
            .ok_or_else(|| invalid("invalid IPC footer bounds"))?;
        let footer =
            root_as_footer(&buffer[start..trailer]).map_err(|_| invalid("invalid IPC footer"))?;
        let schema = Arc::new(fb_to_schema(
            footer
                .schema()
                .ok_or_else(|| invalid("missing IPC schema"))?,
        ));
        // Do not silently copy misaligned input arrays into private buffers.
        let mut decoder = FileDecoder::new(schema, footer.version()).with_require_alignment(true);
        if let Some(dictionaries) = footer.dictionaries() {
            for block in dictionaries {
                decoder.read_dictionary(block, &block_buffer(&buffer, block, start)?)?;
            }
        }
        let blocks = footer
            .recordBatches()
            .map(|blocks| blocks.iter().copied().collect())
            .unwrap_or_default();
        Ok(Self {
            buffer,
            decoder,
            blocks,
            data_end: start,
        })
    }

    pub fn len(&self) -> usize {
        self.blocks.len()
    }
    pub fn is_empty(&self) -> bool {
        self.blocks.is_empty()
    }

    pub fn batch(&self, index: usize) -> Result<RecordBatch, ArrowError> {
        let block = self
            .blocks
            .get(index)
            .ok_or_else(|| invalid("batch index out of bounds"))?;
        let bytes = block_buffer(&self.buffer, block, self.data_end)?;
        self.decoder
            .read_record_batch(block, &bytes)?
            .ok_or_else(|| invalid("record batch missing"))
    }
}

fn block_buffer(
    buffer: &Buffer,
    block: &arrow_ipc::Block,
    limit: usize,
) -> Result<Buffer, ArrowError> {
    let start = usize::try_from(block.offset()).map_err(|_| invalid("negative IPC offset"))?;
    let metadata =
        usize::try_from(block.metaDataLength()).map_err(|_| invalid("negative metadata size"))?;
    let body = usize::try_from(block.bodyLength()).map_err(|_| invalid("negative body size"))?;
    let len = metadata
        .checked_add(body)
        .ok_or_else(|| invalid("IPC block overflow"))?;
    let end = start
        .checked_add(len)
        .filter(|end| *end <= limit)
        .ok_or_else(|| invalid("IPC block outside file"))?;
    let bytes = buffer.slice_with_length(start, end - start);
    let prefix = if bytes.starts_with(&[255, 255, 255, 255]) {
        8
    } else {
        4
    };
    let message_bytes = bytes
        .get(prefix..metadata)
        .ok_or_else(|| invalid("invalid IPC metadata bounds"))?;
    let message =
        arrow_ipc::root_as_message(message_bytes).map_err(|_| invalid("invalid IPC message"))?;
    let compressed = message
        .header_as_record_batch()
        .and_then(|batch| batch.compression())
        .is_some()
        || message
            .header_as_dictionary_batch()
            .and_then(|batch| batch.data())
            .and_then(|batch| batch.compression())
            .is_some();
    if compressed {
        return Err(invalid("shared mmap input must be uncompressed"));
    }
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use arrow_array::{Decimal128Array, Int64Array, StringArray, TimestampNanosecondArray};
    use arrow_ipc::writer::FileWriter;

    #[test]
    fn arrays_reference_mapping_and_outlive_reader() {
        let folder = tempfile::tempdir().unwrap();
        let path = folder.path().join("batch.arrow");
        let batch = RecordBatch::try_from_iter(vec![(
            "value",
            Arc::new(Int64Array::from(vec![1, 2, 3])) as _,
        )])
        .unwrap();
        let mut writer =
            FileWriter::try_new(File::create(&path).unwrap(), &batch.schema()).unwrap();
        writer.write(&batch).unwrap();
        writer.finish().unwrap();
        drop(writer);
        // SAFETY: this test never mutates the published inode.
        let reader = unsafe { MappedIpc::open(&path) }.unwrap();
        let result = reader.batch(0).unwrap();
        let values = result
            .column(0)
            .as_any()
            .downcast_ref::<Int64Array>()
            .unwrap();
        let address = values.values().as_ptr() as usize;
        let base = reader.buffer.as_ptr() as usize;
        assert!(address >= base && address + 24 <= base + reader.buffer.len());
        drop(reader);
        assert_eq!(values.values().as_ref(), &[1, 2, 3]);
        assert_eq!(result, batch);
    }

    #[test]
    fn malformed_file_is_rejected() {
        let folder = tempfile::tempdir().unwrap();
        let path = folder.path().join("bad.arrow");
        std::fs::write(&path, b"not an IPC file").unwrap();
        assert!(unsafe { MappedIpc::open(path) }.is_err());
    }

    #[test]
    fn typed_event_columns_and_nulls_are_preserved() {
        let folder = tempfile::tempdir().unwrap();
        let path = folder.path().join("events.arrow");
        let batch = RecordBatch::try_from_iter(vec![
            (
                "event_type",
                Arc::new(StringArray::from(vec![
                    Some("quote"),
                    None,
                    Some("settlement"),
                ])) as arrow_array::ArrayRef,
            ),
            (
                "price",
                Arc::new(
                    Decimal128Array::from(vec![Some(12345), None, Some(23456)])
                        .with_precision_and_scale(18, 4)
                        .unwrap(),
                ) as _,
            ),
            (
                "event_time",
                Arc::new(TimestampNanosecondArray::from(vec![1, 2, 3]).with_timezone("UTC")) as _,
            ),
        ])
        .unwrap();
        let mut writer =
            FileWriter::try_new(File::create(&path).unwrap(), &batch.schema()).unwrap();
        writer.write(&batch).unwrap();
        writer.finish().unwrap();
        drop(writer);
        let reader = unsafe { MappedIpc::open(&path) }.unwrap();
        let result = reader.batch(0).unwrap();
        let begin = reader.buffer.as_ptr() as usize;
        let end = begin + reader.buffer.len();
        for column in result.columns() {
            let data = column.to_data();
            for buffer in data.buffers() {
                let address = buffer.as_ptr() as usize;
                assert!(address >= begin && address + buffer.len() <= end);
            }
        }
        drop(reader);
        assert_eq!(result, batch);
    }
}
