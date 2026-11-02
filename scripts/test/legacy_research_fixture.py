"""Historical rows for migration acceptance; never used by application runtime."""
from __future__ import annotations
import hashlib
import secrets
import sqlite3
import time


def seed_share_link(database, *, research_id, actor, redeemed_by="", mode="one_time"):
    token = secrets.token_urlsafe(32)
    link_id = "share-" + secrets.token_hex(12)
    now = time.time()
    with sqlite3.connect(database) as db:
        db.execute('''INSERT INTO research_catalog_share_links
            (link_id,target_kind,research_id,report_id,owner_ref,token_hash,mode,
             expires_at,redeemed_by,redeemed_at,revoked_at,created_at)
            VALUES (?, 'research', ?, '', ?, ?, ?, 0, ?, ?, 0, ?)''',
            (link_id, research_id, actor, hashlib.sha256(token.encode()).hexdigest(), mode,
             redeemed_by, now if redeemed_by else 0, now))
    return {"link_id": link_id, "token": token}
