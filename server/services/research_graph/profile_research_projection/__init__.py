"""Bounded, read-only research projections for local Agent Profiles."""

from .indexes import ensure_profile_research_indexes
from .service import ProfileResearchProjection
from .refs import projection_etag

__all__ = [
    "ProfileResearchProjection",
    "ensure_profile_research_indexes",
    "projection_etag",
]
