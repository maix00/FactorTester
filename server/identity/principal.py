"""Small runtime principal value used by the legacy research engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(eq=False)
class Principal:
    """Non-authoritative identity label for request-scoped engine state.

    Authorization comes from a verified Keycloak session or FGAP decision;
    this object only carries a name through older factor-engine APIs.
    """

    name: str
    is_admin: bool = False

    def __post_init__(self) -> None:
        self.name = str(self.name or "")
        parts = self.name.rsplit("@", 1)
        if len(parts) == 2 and parts[1].isdigit():
            self.alias = parts[0].split("@", 1)[-1]
            self.serial = int(parts[1])
        else:
            self.alias = self.name
            self.serial = 1
        self.desc = f"用户 {self.alias}"

    @property
    def testers(self) -> list:
        return []

    def add_tester(self, tester: object) -> None:
        del tester

    def remove_tester(self, tester: object) -> None:
        del tester

    def cleanup_testers(self) -> None:
        from server.services.page_runtime import cleanup_user_pages

        cleanup_user_pages(self)
