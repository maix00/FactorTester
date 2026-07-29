"""SQL owned by the profile research read model."""

from .detail import (
    BRANCH_DETAIL_SQL,
    WORK_PACKAGE_BRANCH_DETAIL_SQL,
    WORK_PACKAGE_DETAIL_SQL,
)
from .listing import LIST_AFTER_SQL, LIST_FIRST_SQL
from .checkpoint import REPORT_CHECKPOINT_SQL
from .timeline import (
    TIMELINE_AFTER_SQL,
    TIMELINE_FIRST_SQL,
    TIMELINE_PLACEMENT_SQL,
    WORK_PACKAGE_TIMELINE_AFTER_SQL,
    WORK_PACKAGE_TIMELINE_FIRST_SQL,
    WORK_PACKAGE_TIMELINE_PLACEMENT_SQL,
)

__all__ = [name for name in globals() if name.endswith("_SQL")]
