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

Use one governance sequence after publication:

1. reserve and settle one real proposer invocation;
2. propose with an `auth-conversation:` reference and compact change diff;
3. obtain the required independent review;
4. create a target-version draft shadow instance with
   `research-graph start --shadow-graph-version`;
5. validate that shadow instance against a distinct baseline Run with the same
   RunSpec hash;
6. record the grill audit, obtain exact human authorization, then activate.

`activation-status` is the authoritative compact gate summary. Do not submit
validation before independent review, and do not reuse another Graph version's
shadow instance.

## Activate

Require exact-hash human authorization. Activation never migrates running
research. Record old/new pointers and rollback target. Do not run factor
research, create obligations or alter evidence during activation.

## Continue a branch

Require an explicit user request and deterministic source-to-target preflight.
The target must be reachable through one complete immutable parent lineage and
must contain the branch's current node. Historical transitions remain bound to
their original Graph versions; do not require every previously visited node or
edge to exist in the target.

Compute the cumulative Change Manifest once. Preserve the same Work Package and
logical branch. Enter the target node through its derived re-entry gate; do not
create a migration node, repeat capability/data/semantics stages mechanically,
or let the maintenance Agent invent factor-specific obligations.

When the branch already has an open capability detour, assess only the current
node's added or revised requirements first. Retain the same episode and
`resume_node`, complete capability recovery, and return through the explicit
resume edge. Assess remaining upgrade requirements only when their owning node
is entered. Never nest a second capability detour inside the open episode.

The Research Agent handles only triggered semantic work: requirement coverage,
obligation reclassification/reopening/creation, evidence qualification and
itemized Chinese report content. Existing evidence remains immutable and is
reused where scope, provenance and timing remain valid.
