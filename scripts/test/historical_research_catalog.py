"""Frozen historical policy oracle for migration fixtures only.

Application modules must never import this fixture. It builds pre-Keycloak
snapshots so parity checks can compare historical allow sets independently.
"""
from typing import Any
from tools.data.sqlite.db import connect_sqlite
from server.manager.services.research_catalog import ResearchCatalog, _access, _loads_list


class HistoricalResearchCatalog(ResearchCatalog):
    def __init__(self, database, *, account_provider=None, **kwargs):
        self._account_provider = account_provider
        super().__init__(database, **kwargs)

    def create_research(self, **kwargs):
        self._seeding_historical_row = True
        try:
            return super().create_research(**kwargs)
        finally:
            self._seeding_historical_row = False

    def require_keycloak_research_creation(self):
        if self._research_authorizer is None and getattr(self, "_seeding_historical_row", False):
            return
        return super().require_keycloak_research_creation()

    def _research_access_values(
        self,
        *,
        research_id: str,
        owner: str,
        status: str,
        visibility: str,
        authorized_users_json: Any,
        viewer: str,
        membership=None,
        profile_access=None,
        keycloak_access=None,
    ) -> dict[str, Any]:
        if self._research_authorizer is not None:
            return super()._research_access_values(research_id=research_id, owner=owner,
                status=status, visibility=visibility, authorized_users_json=authorized_users_json,
                viewer=viewer, membership=membership, profile_access=profile_access,
                keycloak_access=keycloak_access)
        if viewer and viewer == owner:
            return _access(True, True, True, True, "owner", research_id)
        if status == "archived":
            return _access(False, False, False, False, "none", research_id)
        if self._profile_authorizer is not None and (profile_access or {}).get("can_view"):
            return _access(True, True, bool(profile_access.get("can_download")), False, "research", research_id)
        if self._profile_authorizer is None and membership is not None and str(membership["status"]) == "active":
            return _access(
                True, True, True,
                False,  # Membership grants collaboration, never research administration.
                "research", research_id,
            )
        if visibility == "public":
            return _access(True, True, True, False, "research", research_id)
        if visibility == "superiors" and self._is_superior(viewer, owner):
            return _access(True, True, True, False, "research", research_id)
        if viewer and viewer in _loads_list(authorized_users_json):
            return _access(True, True, True, False, "research", research_id)
        return _access(False, False, False, False, "none", research_id)

    def _report_access(
        self, row, viewer: str | None, *, research_access=None, keycloak_access=None,
    ) -> dict[str, Any]:
        viewer_ref = str(viewer or "").strip()
        if self._research_authorizer is not None:
            return super()._report_access(row, viewer, research_access=research_access,
                                          keycloak_access=keycloak_access)
        if viewer_ref and viewer_ref == str(row["owner_ref"]):
            return _access(True, True, True, True, "owner", str(row["report_id"]))
        if research_access is None:
            try:
                research = self._research_row(str(row["research_id"]))
            except KeyError:
                research = None
            if research is not None:
                research_access = self._research_access(research, viewer_ref)
        if research_access and research_access["can_view"]:
            return _access(
                True,
                True,
                research_access["can_download"],
                research_access["can_manage"],
                research_access["access_basis"],
                str(row["report_id"]),
            )
        if str(row["visibility"]) == "public":
            return _access(True, True, False, False, "report", str(row["report_id"]))
        if str(row["visibility"]) == "superiors" and self._is_superior(
            viewer_ref, str(row["owner_ref"]),
        ):
            return _access(True, True, False, False, "report", str(row["report_id"]))
        if viewer_ref and viewer_ref in _loads_list(row["authorized_users_json"]):
            return _access(True, True, False, False, "report", str(row["report_id"]))
        return _access(False, False, False, False, "none", str(row["report_id"]))

    def _is_superior(self, viewer: str, owner: str) -> bool:
        """Resolve the owner's active parent chain from the account authority."""
        if not viewer or not owner or not callable(self._account_provider):
            return False
        try:
            accounts = list(self._account_provider() or [])
        except (OSError, RuntimeError, TypeError, ValueError):
            return False
        by_username = {
            str(item.get("username") or "").strip(): item
            for item in accounts if isinstance(item, dict)
        }
        current = owner
        visited: set[str] = set()
        while current and current not in visited:
            visited.add(current)
            account = by_username.get(current)
            if account is None or account.get("active", True) is False:
                return False
            parent = str(account.get("parent_username") or "").strip()
            if parent == viewer:
                superior = by_username.get(parent)
                return superior is not None and superior.get("active", True) is not False
            current = parent
        return False

    def can_read_authoring_publication(self, record, viewer):
        if self._profile_authorizer is not None:
            return super().can_read_authoring_publication(record, viewer)
        if not viewer or not self.can_read_publication(record, viewer):
            return False
        row = self._report_row(str(record["report_id"]))
        if str(row["owner_ref"]) == viewer:
            return True
        with connect_sqlite(self.db_path, readonly=True) as conn:
            return conn.execute(
                """SELECT 1 FROM research_catalog_memberships WHERE research_id=?
                   AND principal_ref=? AND status='active' AND role IN ('owner','editor','contributor')""",
                (str(row["research_id"]), viewer),
            ).fetchone() is not None


    def create_share_link(self, *, target_kind, research_id, actor, report_id="", mode="permanent", expires_at=0):
        if self._research_authorizer is not None:
            return super().create_share_link(target_kind=target_kind, research_id=research_id,
                actor=actor, report_id=report_id, mode=mode, expires_at=expires_at)
        from scripts.test.legacy_research_fixture import seed_share_link
        link = seed_share_link(self.db_path, research_id=research_id, actor=actor, mode=mode,
                               target_kind=target_kind, report_id=report_id)
        with self._write(research_id) as db:
            db.execute("UPDATE research_catalog_share_links SET expires_at=? WHERE link_id=?", (expires_at, link["link_id"]))
        return link

    def redeem_share_link(self, token, *, actor):
        if self._research_authorizer is not None:
            return super().redeem_share_link(token, actor=actor)
        import hashlib, json
        with connect_sqlite(self.db_path) as db:
            link = db.execute("SELECT * FROM research_catalog_share_links WHERE token_hash=?",
                              (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        with self._write(link["research_id"]) as db:
            row = db.execute("SELECT authorized_users_json FROM research_catalog_researches WHERE research_id=?", (link["research_id"],)).fetchone()
            users = sorted(set(_loads_list(row["authorized_users_json"]) + [actor]))
            db.execute("UPDATE research_catalog_researches SET authorized_users_json=? WHERE research_id=?", (json.dumps(users), link["research_id"]))
        return {"research_id": link["research_id"]}
