"""Recoverable link redemption with Keycloak as the sole grant authority."""
from __future__ import annotations

import hashlib
import math
import secrets
import time

from tools.data.sqlite.db import connect_sqlite
from server.identity.keycloak_authorization import AuthorizationUnavailable


def ensure_link_journal(conn):
    """Create link identity/recovery metadata, never an authorization grant."""
    conn.execute("""CREATE TABLE IF NOT EXISTS research_share_link_issuers (
        link_id TEXT PRIMARY KEY, identity_id TEXT NOT NULL, subject TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS research_share_link_claims (
        link_id TEXT NOT NULL, identity_id TEXT NOT NULL, subject TEXT NOT NULL,
        status TEXT NOT NULL, created_at REAL NOT NULL,
        PRIMARY KEY(link_id,identity_id)
    )""")


class ResearchShareLinksMixin:
    def _share_manager(self):
        manager = self._profile_grant_manager
        if manager is None:
            raise RuntimeError("Research links require Keycloak grant migration")
        return manager

    @staticmethod
    def _link_identity(manager, actor):
        caller = manager.identity_provider(actor)
        if caller is None:
            raise PermissionError("Research link requires a verified Keycloak identity")
        try:
            user = manager.user_by_identity(caller.identity_id)
        except (LookupError, AuthorizationUnavailable):
            raise
        except Exception as exc:
            raise AuthorizationUnavailable("Research link identity lookup is unavailable") from exc
        attrs = user.get("attributes") if isinstance(user, dict) else None
        if (not isinstance(user, dict) or user.get("enabled") is not True
                or user.get("id") != caller.subject or not isinstance(attrs, dict)
                or attrs.get("tr_identity_id") != [caller.identity_id]):
            raise PermissionError("Research link identity is unavailable")
        return caller

    @staticmethod
    def _link_target(row):
        kind = str(row["target_kind"])
        if kind == "research":
            return "research", str(row["research_id"]), ("read", "use")
        if kind == "report":
            return "research_report", str(row["report_id"]), ("read",)
        raise ValueError("Research link target is invalid")

    def _create_keycloak_share_link(self, *, target_kind, research_id, report_id,
                                    actor, mode, expires_at):
        if target_kind not in {"research", "report"}:
            raise ValueError("target_kind must be research or report")
        if mode not in {"one_time", "permanent"}:
            raise ValueError("mode must be one_time or permanent")
        manager = self._share_manager()
        research = self._research_row(research_id)
        if not self._research_access(research, actor)["can_manage"]:
            raise PermissionError("research sharing is not authorized")
        kind, target = self._keycloak_share_target(research_id, target_kind, report_id)
        manager.require_resource_share(actor=actor, resource_type=kind, resource_ref=target)
        issuer = self._link_identity(manager, actor)
        token, link_id, now = secrets.token_urlsafe(32), "share-" + secrets.token_hex(12), time.time()
        expiry = float(expires_at or 0)
        if not math.isfinite(expiry):
            raise ValueError("share link expiry is invalid")
        expiry = max(0.0, expiry)
        with connect_sqlite(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""INSERT INTO research_catalog_share_links
                (link_id,target_kind,research_id,report_id,owner_ref,token_hash,mode,
                 expires_at,redeemed_by,redeemed_at,revoked_at,created_at)
                VALUES (?,?,?,?,?,?,?,?,'',0,0,?)""",
                (link_id, target_kind, research_id, report_id, actor,
                 hashlib.sha256(token.encode("utf-8")).hexdigest(), mode, expiry, now))
            conn.execute("""INSERT INTO research_share_link_issuers
                (link_id,identity_id,subject) VALUES (?,?,?)""",
                (link_id, issuer.identity_id, issuer.subject))
        return {"link_id": link_id, "target_kind": target_kind, "research_id": research_id,
                "report_id": report_id, "mode": mode, "expires_at": expiry,
                "token": token, "created_at": now}

    def _redeem_keycloak_share_link(self, token, *, actor):
        value = str(token or "").strip()
        if not value or len(value) > 512:
            raise ValueError("token is invalid")
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        manager = self._share_manager()
        caller = self._link_identity(manager, actor)

        def checked_link(conn):
            row = conn.execute("""SELECT l.*,i.identity_id AS issuer_identity_id,
                i.subject AS issuer_subject FROM research_catalog_share_links l
                LEFT JOIN research_share_link_issuers i ON i.link_id=l.link_id
                WHERE l.token_hash=?""", (digest,)).fetchone()
            if row is None:
                raise KeyError("share link not found")
            revoked, expiry = float(row["revoked_at"]), float(row["expires_at"])
            if not math.isfinite(revoked) or not math.isfinite(expiry) or revoked < 0 or expiry < 0:
                raise RuntimeError("Research share link needs time repair")
            if revoked > 0:
                raise KeyError("share link not found")
            if expiry > 0 and expiry <= time.time():
                raise PermissionError("share link has expired")
            if not row["issuer_identity_id"] or not row["issuer_subject"]:
                raise RuntimeError("Research share link needs identity migration")
            if str(row["mode"]) not in {"one_time", "permanent"}:
                raise RuntimeError("Research share link needs mode repair")
            kind, target, _scopes = self._link_target(row)
            if not target:
                raise RuntimeError("Research share link needs target repair")
            research = conn.execute("SELECT status FROM research_catalog_researches WHERE research_id=?",
                                    (row["research_id"],)).fetchone()
            if research is None or research["status"] != "active":
                raise KeyError("shared Research is unavailable")
            if kind == "research_report":
                report = conn.execute("SELECT research_id,status FROM research_catalog_reports WHERE report_id=?",
                                      (target,)).fetchone()
                if (report is None or report["research_id"] != row["research_id"]
                        or report["status"] != "active"):
                    raise KeyError("shared report is unavailable")
            return row, kind, target

        # Fail before consuming a one-time link if the issuer is already
        # revoked or Keycloak is offline. Recheck inside the serialized write
        # below, so a stale decision is not used for the actual grant.
        with connect_sqlite(self.db_path, readonly=True) as conn:
            first, kind, target = checked_link(conn)
        manager.require_link_issuer_share(identity_id=str(first["issuer_identity_id"]),
            subject=str(first["issuer_subject"]), research_id=str(first["research_id"]),
            resource_type=kind, resource_ref=target)

        # Persist the exact claimant *before* touching Keycloak. If a process
        # dies after a grant succeeded, a one-time link cannot be claimed by a
        # second user; the original user can safely retry the same policy.
        with connect_sqlite(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row, _kind, _target = checked_link(conn)
            link_id = str(row["link_id"])
            if str(row["mode"]) == "one_time":
                previous = conn.execute("""SELECT identity_id,subject FROM research_share_link_claims
                    WHERE link_id=? LIMIT 2""", (link_id,)).fetchall()
                if len(previous) > 1:
                    raise RuntimeError("Research share link has conflicting claimants")
                if str(row["redeemed_by"]) and not previous:
                    raise RuntimeError("Research share link needs redemption migration")
                if any(str(item["identity_id"]) != caller.identity_id for item in previous):
                    raise PermissionError("share link has already been redeemed")
            else:
                previous = conn.execute("""SELECT identity_id,subject FROM research_share_link_claims
                    WHERE link_id=? AND identity_id=?""", (link_id, caller.identity_id)).fetchall()
            matching = [item for item in previous if str(item["identity_id"]) == caller.identity_id]
            if matching and str(matching[0]["subject"]) != caller.subject:
                raise RuntimeError("Research share link claimant needs identity migration")
            if not matching:
                conn.execute("""INSERT INTO research_share_link_claims
                    (link_id,identity_id,subject,status,created_at) VALUES (?,?,?,'pending',?)""",
                    (link_id, caller.identity_id, caller.subject, time.time()))
                if str(row["mode"]) == "one_time":
                    conn.execute("UPDATE research_catalog_share_links SET redeemed_by=?,redeemed_at=? WHERE link_id=?",
                                 (actor, time.time(), link_id))

        # Serialize grant and revoke through SQLite. Link redemption is an
        # infrequent control-plane action; no market-data path takes this lock.
        with connect_sqlite(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row, kind, target = checked_link(conn)
            link_id = str(row["link_id"])
            claim = conn.execute("""SELECT subject,status FROM research_share_link_claims
                WHERE link_id=? AND identity_id=?""", (link_id, caller.identity_id)).fetchone()
            if claim is None or str(claim["subject"]) != caller.subject:
                raise PermissionError("Research link claim is no longer valid")
            manager.require_link_issuer_share(identity_id=str(row["issuer_identity_id"]),
                subject=str(row["issuer_subject"]), research_id=str(row["research_id"]),
                resource_type=kind, resource_ref=target)
            _kind, _target, scopes = self._link_target(row)
            try:
                manager._reconcile_user_grant(resource_type=kind, resource_ref=target,
                    source="link:" + link_id, identity_id=caller.identity_id,
                    subject=caller.subject, scopes=scopes)
            except (LookupError, ValueError, AuthorizationUnavailable):
                raise
            except Exception as exc:
                raise AuthorizationUnavailable("Research link grant is unavailable") from exc
            conn.execute("""UPDATE research_share_link_claims SET status='applied'
                WHERE link_id=? AND identity_id=?""", (link_id, caller.identity_id))
        return {"target_kind": str(row["target_kind"]), "research_id": str(row["research_id"]),
                "report_id": str(row["report_id"]), "mode": str(row["mode"])}
