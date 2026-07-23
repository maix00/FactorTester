# Graph version governance

Keep three operations distinct:

- **publish** creates one immutable reviewed Graph version;
- **activate** changes only the default pointer for new research;
- **continue** explicitly moves one eligible Work Package branch to a
  descendant Graph while preserving its immutable history.

## Publish

Validate schema, parent lineage, content hash, Requirement Catalog, resolver
coverage, Report Methods, capability descriptors, topology, Change Manifest,
token bounds and replay/shadow evidence. A Graph with any active subcategory
that lacks a real resolver and report contract remains draft-only.

## Activate

Require exact-hash human authorization. Activation never migrates running
research. Record old/new pointers and rollback target. Do not run factor
research, create obligations or alter evidence during activation.

## Continue a branch

Require an explicit user request and deterministic source-to-target preflight.
The target must contain the same current node. Reject continuation when the
branch history touched a removed or semantically unmapped node/edge.

Compute the cumulative Change Manifest once. Preserve the same Work Package and
logical branch. Enter the target node through its derived re-entry gate; do not
create a migration node, repeat capability/data/semantics stages mechanically,
or let the maintenance Agent invent factor-specific obligations.

The Research Agent handles only triggered semantic work: requirement coverage,
obligation reclassification/reopening/creation, evidence qualification and
itemized Chinese report content. Existing evidence remains immutable and is
reused where scope, provenance and timing remain valid.
