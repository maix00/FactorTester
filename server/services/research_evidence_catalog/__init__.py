"""Public fragment-bound Evidence catalog service."""

from .lifecycle import (
    change_evidence_status,
    get_evidence_lifecycle,
    require_active_evidence,
)
from .listing import (
    get_evidence_summary,
    list_evidence_page,
    list_evidence_relationship_page,
    list_research_evidence_page,
)
from .search import list_facets, search_evidence
from .sources import (
    capture_job_source,
    create_evidence,
    create_source_fragment,
    evidence_contains_job_source,
    evidence_source,
    find_job_evidence,
    get_composed_evidence,
    get_source_capture,
    list_source_fragments,
    put_source_capture,
    put_source_fragment,
    update_evidence_applicability,
)
from .tags import (
    attach_tag,
    create_tag,
    detach_tag,
    list_tags,
    propose_tag,
    retire_tag,
    update_tag,
)

__all__ = [
    "attach_tag",
    "capture_job_source",
    "create_evidence",
    "create_source_fragment",
    "create_tag",
    "detach_tag",
    "evidence_contains_job_source",
    "evidence_source",
    "change_evidence_status",
    "find_job_evidence",
    "get_composed_evidence",
    "get_evidence_lifecycle",
    "get_evidence_summary",
    "get_source_capture",
    "list_evidence_page",
    "list_evidence_relationship_page",
    "list_facets",
    "list_research_evidence_page",
    "list_source_fragments",
    "list_tags",
    "propose_tag",
    "put_source_capture",
    "put_source_fragment",
    "require_active_evidence",
    "retire_tag",
    "search_evidence",
    "update_evidence_applicability",
    "update_tag",
]
