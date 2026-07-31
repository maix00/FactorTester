# Graph version governance

Keep three operations distinct:

- **publish** creates one immutable reviewed Graph version;
- **activate** changes only the default pointer for new research;
- **continue** explicitly moves one eligible Work Package branch to a
  descendant Graph while preserving its immutable history.

## Publish

Validate schema, parent lineage, content hash, Requirement Catalog, resolver
coverage, Report Methods, capability descriptors, topology, Change Manifest
and token bounds. A Graph with any active subcategory that lacks a real
resolver and report contract remains draft-only.

Use one governance sequence after publication:

1. reserve and settle one real proposer invocation;
2. propose with an `auth-conversation:` reference and compact change diff;
3. have the independent reviewer read the exact server-owned packet with
   `research-graph proposal <proposal-id>`, inspect its immutable target,
   Change Manifest and evidence references, then submit the disposition using
   the returned command contract;
4. inspect `research-graph activation-status <graph-id> <version>`;
5. activate with `research-graph activate <graph-id> <version> --yes`.

`activation-status` is the authoritative compact gate summary. Activation
derives deterministic upgrade validation inside one transaction and rolls back
all temporary instance, branch and trace rows before moving the pointer. It
never creates a persistent validation Work Package. A grill record is optional
unless the reviewed Graph contract explicitly requires one. The proposer must
not send a reconstructed review summary in place of
`research-graph proposal`; the reviewer principal and lineage must both be
independent and the reviewer invocation must already be settled.

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

Compute the cumulative Change Manifest once. Continuation preserves the same
Work Package and logical Hypothesis Branch while creating a new physical
incarnation bound to the target Graph version. Use `fork` only when the user
intends a distinct research path; never use a fork or a persistent temporary
branch to validate a Graph upgrade.

Enter the target node through its derived re-entry gate; do not create a
migration node, repeat capability/data/semantics stages mechanically, or let
the maintenance Agent invent factor-specific obligations.

When the branch already has an open capability detour, assess only the current
node's added or revised requirements first. Retain the same episode and
`resume_node`, complete capability recovery, and return through the explicit
resume edge. Assess remaining upgrade requirements only when their owning node
is entered. Never nest a second capability detour inside the open episode.

The Research Agent handles only triggered semantic work: requirement coverage,
obligation reclassification/reopening/creation, evidence qualification and
itemized Chinese report content. Existing evidence remains immutable and is
reused where scope, provenance and timing remain valid.
