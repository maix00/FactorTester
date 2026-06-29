"""Strategy — a lightweight per-strategy identity object, same base class
as Product so it can be used directly as a dict key (UniqueNameObject
implements __eq__/__hash__)."""

from __future__ import annotations

from tools.data.types.base import UniqueNameObject


class Strategy(UniqueNameObject):
    """name is "<shortAlias>:<32-hex-uuid>". The frontend passes alias=
    shortAlias (not name); UniqueNameObject.__new__ auto-generates the
    uuid-suffixed name. Constructing again with the same name returns the
    same (deduplicated) instance."""
