from __future__ import annotations

from server.manager.storage.agent_skill_store import AgentSkillStore
from tools.data.sqlite.db import connect_sqlite


def test_renamed_trade_research_skill_selections_are_migrated(tmp_path) -> None:
    database = tmp_path / "manager.sqlite"
    store = AgentSkillStore(database)
    with connect_sqlite(database) as connection:
        connection.execute(
            """INSERT INTO manager_profile_skill_selections
               (principal, profile_id, skill_id, selected_at)
               VALUES (?, ?, ?, ?)""",
            ("user:123", "profile:abc", "factortester-research", 42.0),
        )

    migrated = AgentSkillStore(database)

    assert migrated.selected("user:123", "profile:abc") == [
        "traderesearch-research",
    ]


def test_skill_id_migration_deduplicates_existing_canonical_selection(tmp_path) -> None:
    database = tmp_path / "manager.sqlite"
    AgentSkillStore(database)
    with connect_sqlite(database) as connection:
        connection.executemany(
            """INSERT INTO manager_profile_skill_selections
               (principal, profile_id, skill_id, selected_at)
               VALUES (?, ?, ?, ?)""",
            [
                ("user:123", "profile:abc", "factortester-research", 42.0),
                ("user:123", "profile:abc", "traderesearch-research", 43.0),
            ],
        )

    migrated = AgentSkillStore(database)

    assert migrated.selected("user:123", "profile:abc") == [
        "traderesearch-research",
    ]
