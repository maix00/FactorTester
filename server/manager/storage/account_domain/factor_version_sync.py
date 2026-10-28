"""Advertise locally held immutable formula versions without loading bodies."""

from tools.data.sqlite.db import connect_sqlite


def backfill_factor_versions(sync, owner: str) -> int:
    count = 0
    with connect_sqlite(sync.local.path) as connection:
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='factor_family_formula_versions'"
        ).fetchone():
            return 0
        rows = connection.execute(
            "SELECT source_kind, owner_username, factor_id, family_formula_fingerprint, "
            "source_sha256, subject, created_at, length(CAST(source_code AS BLOB)) AS source_bytes "
            "FROM factor_family_formula_versions WHERE source_kind='public' OR owner_username=?",
            (owner,),
        ).fetchall()
        for row in rows:
            payload = dict(row)
            kind, username, factor = row['source_kind'], row['owner_username'], row['factor_id']
            payload.update(storage_server_id=sync.manager_id, factor_name=factor,
                           visibility='public' if kind == 'public' else 'private')
            operation = sync.local.upsert_local(
                principal=username or '__public__', entity_type='factor_source_version',
                entity_id=f"{kind}:{factor}:{row['family_formula_fingerprint']}@{sync.manager_id}",
                payload=payload, manager_id=sync.manager_id, connection=connection,
            )
            from server.services.versioning import build_revision_manifest, enqueue_revision

            manifest = build_revision_manifest(
                object_kind="factor_family",
                object_ref=f"factor-family:{kind}:{username or 'public'}:{factor}",
                revision_ref=f"factor-family-revision:{row['family_formula_fingerprint']}",
                content_sha256=str(row["source_sha256"]),
                owner_ref=username or "__public__",
                storage_server_id=sync.manager_id,
                created_at=float(row["created_at"]),
                created_by=username or "platform",
                visibility="public" if kind == "public" else "private",
                object_bytes=int(row["source_bytes"] or 0),
                source_entity_type="factor_source_version",
            )
            enqueue_revision(
                sync.local,
                principal=username or "__public__",
                manager_id=sync.manager_id,
                manifest=manifest,
                connection=connection,
            )
            count += bool(operation)
    return count
