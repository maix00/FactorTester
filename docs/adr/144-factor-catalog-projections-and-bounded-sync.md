# ADR 144: Factor catalog read projections and bounded synchronization

Status: accepted for issue #372 (2026-09-06).

## Evidence

Using testA under the same direct-child scope, local/public Managers showed 40/20 factors and 1/0 sets. Seventeen authority config tombstones carried an incompatible-identity migration reason; thirteen accounted for the missing twenty factors. CAS rejection remained retryable and produced over 50,000 duplicate local conflict observations. The current v2 authored set uses `ref` and frozen members, while sync reconciliation and remote detail still expected v1 fields.

A synthetic comparison with the same repository JavaScript and DOM stubs measured 10,000-row search/render at 51.5 ms before and 1.08 ms after; off-page action buttons fell from 20,000 to 40. Expanding 1,000 IC candidates fell from 278 ms to 0.17 ms. These measurements exclude browser layout, network and source-specific execution.

## Decision

Reuse the existing account-domain mirror/outbox/control authority and the existing `factor_family_catalog`, rather than adding another transport or database. Family source writes persist source-free catalog JSON with the source hash; explicit backfill handles legacy rows. Ordinary list reads never import factor source, instantiate a family, repair metadata or wait for remote reconciliation.

Store individual factor read projections under the local-only `factor_catalog_entry` kind in the existing account-domain entity store, indexed by principal/config and principal/factor ref. They are updated in the same transaction as a complete frozen configuration and are excluded from generic entity listings and the outbox. Unresolved authoring drafts retain the last valid factor projections. Candidate lookup and paging can query these indexed rows without parsing every parameter configuration.

Keep parameter configuration JSON as the compatible authoring and sync input for this rollout. It is not the list's read model. Reconciliation freezes missing legacy records and raw pending drafts produced by explicit authoring write hooks; immutable records and source summaries are reused. A retained authored copy must never replace a complete frozen mirror or resurrect its tombstone after a Manager restart. A future change to per-registration wire mutations needs a separate versioned rollout covering cross-server editing, delete intent, scope membership and partial-generation visibility. Do not disguise that protocol change as a local cache migration. Reject oversized metadata explicitly; never silently truncate identity graphs or member lists.

Conflicts preserve both values, block ordinary retries, and deduplicate equal observations. Explicit resolution checks the local payload and latest observed remote revision, then uses normal authority CAS again. An acknowledgement for a coalesced in-flight write rebases its successor without overwriting its new payload. Collection absence, missing dependencies and conversion failure are not deletion intent. Only explicit delete paths publish tombstones; default deployment migration must not use `--discard-incompatible`.

Authored and mirrored sets share v2 validation, summaries, paged frozen members and RunSpec descriptors. Missing source identity is represented as unresolved, never a synthesized formula fingerprint. Source localization requires matching source bytes; on-demand hydration checks the requested/advertised formula fingerprint and uses a local manifest first, then a targeted authority lookup.

## Business fetch boundaries

- List/filter/page: local summaries and projected frozen rows; coalesced principal-scoped asynchronous metadata refresh.
- Open source/version: exact source/version metadata, resident version if present, hash-checked data-plane hydration if absent.
- Open a set: paged frozen members; no eager expansion of every set during catalog loading.
- Add a set to a test: validate all fetched members before one bulk candidate update, retaining provenance and existing scalar primary selection.
- Submit test: freeze and verify only selected dependencies; source absence fails or hydrates the required object, never expands the entire catalog.

The frontend shares an access-scoped catalog cache across lists and test pickers. Refresh/session generations prevent stale responses from overwriting newer data. Search indexes are reused for immutable row objects; table row renderers run after paging.

## Rollout and acceptance

Back up and integrity-check both SQLite stores and restore-check PostgreSQL before recovery. Deploy the source changes and explicitly backfill projections. Recovery must use a deterministic, precondition-checked manifest of validated frozen objects, preserving unrelated rows and user deletion intent. Verify testA direct-child factor refs, set refs and member refs across both Managers, not counts alone. Keep previous deployment revisions and backups as rollback references. AGENTS workflow changes use its separate main-only route.
