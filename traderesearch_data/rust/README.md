# Shared Arrow input reader

This crate reads immutable, uncompressed Arrow IPC files published by the
`traderesearch_data.shared_cache` producer. It has no dependency on Python,
platform Product objects, a particular market-data schema, or Nautilus.

Schema, field metadata, decimal precision, timestamp units/timezones, nulls and
event types remain those of the input Arrow batch. Consumers select compatible
columns or perform explicit conversions at their own integration boundary.
Cache identity, authorization, revision invalidation, admission and eviction
remain in the existing producer; this reader does not duplicate those policies.

`MappedIpc::open` is unsafe because callers must guarantee that published inodes
are never modified or truncated while borrowed. Atomic replacement is allowed.
The existing cache follows this contract. Arrow buffers retain their mapping
through reference-counted ownership after the reader is dropped. Validation is
enabled; compressed or misaligned input is rejected rather than silently
allocating private value buffers. RecordBatch/schema metadata still allocates.

This reader alone does not connect Nautilus `run_catalogs` to the shared cache.
Raw Bundle schemas and Nautilus event schemas may require different buffers.
Connecting the execution consumer must preserve native event precision/order
and streaming bounds; adding a Python per-event replay loop is not acceptable.

Focused verification:

```sh
cargo test --manifest-path traderesearch_data/rust/Cargo.toml
cargo run --manifest-path traderesearch_data/rust/Cargo.toml --example inspect_ipc -- /absolute/immutable/cache.arrow
```

Build outputs should use an external `CARGO_TARGET_DIR`. The inspector reports
batch/row counts, not performance or proof of whole-path zero-copy execution.
