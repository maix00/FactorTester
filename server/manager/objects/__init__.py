"""Domain objects that can be carried by the Manager data plane."""

from server.manager.objects.models import ObjectReference, TransferObjectKind
from server.manager.objects.destination import ObjectDestinationRegistry
from server.manager.objects.references import (
    research_object_id,
    split_research_object_id,
)

__all__ = [
    "ObjectReference",
    "ObjectDestinationRegistry",
    "TransferObjectKind",
    "research_object_id",
    "split_research_object_id",
]
