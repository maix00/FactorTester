# ADR-040: Derived Research Reports

## Status

Accepted.

## Context

Factor research produces immutable contracts, claims, obligations, trial plans,
evidence envelopes, job records, graph traces, and local Agent notes. These
objects must remain independently addressable for replay and audit. A human
reader also needs a coherent research narrative, but neither one ever-growing
Markdown file nor a new report database should become another source of truth.

Future reports may include charts and may also be rendered as PDF. Charts are
components within a report; Markdown and PDF are render targets for the same
bounded report model.

## Decision

Research reports are deterministic, local, cold-path projections over explicit
object references. Report generation does not call an LLM, execute a Skill,
advance the Active Graph, or write server research tables. It assembles only
facts, accepted Agent-authored notes, and content-addressed assets already
present in its input snapshot.

The canonical research objects and Graph trace remain authoritative. Generated
reports are disposable and rebuildable. A report records the graph,
methodology, Decision Contract, factor-family version, TrialPlan, and evidence
hashes from which it was built; it never replaces those objects.

One monolithic file is rejected. Reports belong to the Profile research root,
not to its factor-authoring worktree. The derived local layout is:

```text
research/<work-package-id>/
  INDEX.json
  REPORT.md
  branches/<branch-id>/REPORT.md
  assets/
```

- `INDEX.json` is a bounded deterministic UI projection and commit point, not
  a canonical record or database object.
- The Work Package `REPORT.md` is a derived aggregate.
- A branch report presents one bounded research lineage.
- Immutable evidence and result artifacts remain in their existing stores and
  are linked by reference rather than copied inline.
- Agent notes remain separate inputs so a renderer cannot silently rewrite
  provisional reasoning as server fact.

The renderer boundary accepts a bounded snapshot, not a live database handle:

```text
ReportSnapshot
  -> ReportDocument(sections, evidence_refs, asset_refs, source_hash)
  -> ReportRenderer
  -> MarkdownTarget | PdfTarget
```

`ReportDocument` contains ordered sections and references. `ReportAsset`
contains a content hash, media type, caption, provenance references, and
optional accessibility text. A chart is one `ReportAsset`; it is embedded in a
section and is not a separate report type. A later chart producer may create
assets from reviewed result data, but the report renderer only verifies and
places them.

Only Markdown rendering is required by the first implementation. The public
interfaces reserve additional render targets and assets without importing a
PDF or chart dependency now. PDF generation and chart production require their
own later acceptance tests and ADR update.

Sync and rendering are separate:

1. An explicit local sync obtains only changed compact objects and artifact
   references.
2. The renderer reads that bounded local snapshot and performs zero database
   and network reads.
3. A per-Work-Package file lock serializes index load, merge, staging, and
   publication without adding a database transaction or event object.
4. Unchanged bytes reuse all report files. Changed branch, aggregate, and index
   files are staged first and published in that order, with `INDEX.json` last.
5. A failed publication restores the previous complete three-file generation.

Workspace regeneration must preserve `research/`. Reports never contain factor
source, private formulas, expression trees, credentials, raw stdout/stderr, or
unbounded result payloads. Access policy and artifact availability are checked
before a reference is rendered.

## Consequences

- Human-readable research history does not create a parallel persistence
  model.
- Report generation has zero model-token cost and a measurable zero-database
  rendering path.
- Large evidence, curves, and charts remain content-addressed assets instead
  of inflating Markdown or Agent context.
- A branch report can be regenerated after a renderer upgrade without changing
  any research conclusion or graph state.
- PDF and chart support can be added without changing the research-object
  protocol, provided they implement the same bounded document and asset
  interfaces.

### Quantitative visualization and navigation boundary

The backend may emit only deterministic, compact series/table artifacts.
Charts and PDF pages are cold-path derived assets over those reviewed
artifacts; they are not additional research results and never trigger a new
database read during report rendering.

The minimum v1 report presentation is:

- the compact result table;
- conditional net-equity and drawdown series when the tested strategy
  semantics make those series meaningful;
- ordered group-return and group-spread series for cross-sectional tests.

Heatmaps and PDF rendering remain deferred. Chart assets remain components
inside Markdown/PDF report sections rather than standalone report records.
Their provenance links to the exact compact backend artifact.

Realized turnover and cost drag, observation count and coverage, the exact
Sharpe and annualization convention, uncertainty for monotonicity claims, and
multiplicity-adjustment references are explicit backend capability gaps. The
client or report renderer must not infer them.

Opening a holdout artifact is an auditable event. The report index retains its
stable holdout reference and access receipt; routine in-sample navigation must
not silently load or display holdout content.

`ProfileResearchProjection` reserves bounded `list`, `detail`, and `timeline`
seams. `ReportDocument` v2 and `INDEX.json` reserve bidirectional stable
anchors between report sections and TrialPlan, obligation, and evidence
references. The UI consumes those projections and anchors rather than reading
database schema or scanning complete Markdown. A future server implementation
must preserve a one-query profile index, at most two detail queries, keyset
timeline pages of at most 50 rows, one cached object lookup per click, and zero
database writes for SSE delivery. This ADR reserves the interface only; it
does not authorize new database objects or server endpoints.

## Acceptance

The first implementation must prove:

- deterministic byte-stable Markdown for the same snapshot;
- incremental rebuild writes only changed report files;
- no database, network, LLM, or Skill call occurs during rendering;
- missing or unauthorized references are rendered as explicit bounded gaps;
- workspace regeneration preserves existing reports and notes;
- report files contain provenance hashes but no prohibited source or heavy
  payload;
- the Markdown target supports embedded, content-addressed report assets;
- stub conformance tests allow later PDF and chart components without making
  either a runtime dependency.
