"""Public fragment-bound Evidence catalog service."""

from .search import list_facets, search_evidence
from .sources import (
    capture_job_source,
    create_evidence,
    find_job_evidence,
    get_composed_evidence,
    get_source_capture,
    list_source_fragments,
    put_source_capture,
    put_source_fragment,
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
    "find_job_evidence",
    "create_tag",
    "detach_tag",
    "get_composed_evidence",
    "get_source_capture",
    "list_facets",
    "list_source_fragments",
    "list_tags",
    "propose_tag",
    "put_source_capture",
    "put_source_fragment",
    "retire_tag",
    "search_evidence",
    "update_tag",
]
