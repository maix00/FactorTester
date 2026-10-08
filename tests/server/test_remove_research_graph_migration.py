from __future__ import annotations

import json
import sqlite3

import pytest

from tools.migrations.remove_research_graph import apply, inspect
from tests.server.test_backend_assurance_migration import (
    _create_legacy_database,
    _insert_job,
)


def _create_database(path):
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE research_catalog_researches (
                research_id TEXT PRIMARY KEY, owner_ref TEXT NOT NULL,
                title TEXT NOT NULL
            );
            INSERT INTO research_catalog_researches VALUES ('research-1', 'alice', 'Study');
            CREATE TABLE research_catalog_reports (
                report_id TEXT PRIMARY KEY, title TEXT NOT NULL
            );
            INSERT INTO research_catalog_reports VALUES ('report-1', 'Report');
            CREATE TABLE research_catalog_branches (
                report_id TEXT NOT NULL, branch_id TEXT NOT NULL,
                content TEXT NOT NULL, PRIMARY KEY(report_id, branch_id)
            );
            INSERT INTO research_catalog_branches VALUES ('report-1', 'main', '正文');
            CREATE TABLE research_catalog_report_evidence_links (
                link_ref TEXT PRIMARY KEY, evidence_ref TEXT NOT NULL,
                evidence_owner_ref TEXT NOT NULL, report_id TEXT NOT NULL,
                branch_ref TEXT NOT NULL, graph_ref TEXT NOT NULL,
                job_id TEXT NOT NULL, profile_ref TEXT NOT NULL,
                purpose TEXT NOT NULL, status TEXT NOT NULL,
                created_at REAL NOT NULL, revoked_at REAL NOT NULL,
                FOREIGN KEY(report_id) REFERENCES research_catalog_reports(report_id)
            );
            INSERT INTO research_catalog_report_evidence_links VALUES (
                'link-1', 'evidence-1', 'alice', 'report-1', 'main',
                'graph-1', 'job-1', 'profile-1', 'analysis', 'active', 1, 0
            );
            CREATE TABLE research_runs (
                run_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                graph_instance_id TEXT NOT NULL, run_spec_json TEXT NOT NULL
            );
            INSERT INTO research_runs VALUES ('run-1', 'alice', 'graph-1', '{"x":1}');
            CREATE TABLE research_jobs (
                job_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, owner TEXT NOT NULL,
                status TEXT NOT NULL, run_spec_hash TEXT NOT NULL DEFAULT '',
                terminal_assurance_json TEXT
            );
            INSERT INTO research_jobs VALUES ('job-1', 'run-1', 'alice', 'succeeded', '', NULL);
            CREATE TABLE research_job_artifacts (
                job_id TEXT NOT NULL, name TEXT NOT NULL, content_hash TEXT NOT NULL,
                size_bytes INTEGER NOT NULL, state TEXT NOT NULL
            );
            INSERT INTO research_job_artifacts VALUES ('job-1', 'result.json', 'hash', 10, 'ready');
            CREATE TABLE research_evidence_objects (
                evidence_ref TEXT PRIMARY KEY, envelope_json TEXT NOT NULL
            );
            INSERT INTO research_evidence_objects VALUES ('evidence-1', '{"claim":"x"}');
            CREATE TABLE research_evidence_admissions (
                admission_ref TEXT PRIMARY KEY, evidence_ref TEXT NOT NULL,
                environment_ref TEXT NOT NULL, subject_ref TEXT NOT NULL,
                qualification TEXT NOT NULL, note TEXT NOT NULL, owner TEXT NOT NULL,
                created_at REAL NOT NULL,
                UNIQUE(evidence_ref, environment_ref, subject_ref)
            );
            INSERT INTO research_evidence_admissions VALUES (
                'admission-graph', 'evidence-1', 'env',
                'graph-branch:instance-1:branch-1', 'eligible', '', 'alice', 1
            );
            INSERT INTO research_evidence_admissions VALUES (
                'admission-report', 'evidence-1', 'env',
                'report:report-1:main', 'eligible', 'keep', 'alice', 2
            );
            INSERT INTO research_evidence_admissions VALUES (
                'admission-graph-instance', 'evidence-1', 'env',
                'research-graph:instance-1', 'eligible', '', 'alice', 3
            );
            CREATE TABLE research_maintenance_cases (
                case_id TEXT PRIMARY KEY, affected_refs_json TEXT NOT NULL,
                change_refs_json TEXT NOT NULL, status TEXT NOT NULL
            );
            INSERT INTO research_maintenance_cases VALUES (
                'case-1', '["job:job-1","work-package:package-1"]',
                '["graph-branch:instance-1:branch-1","evidence:evidence-1"]', 'open'
            );
            CREATE TABLE research_graph_instances (instance_id TEXT PRIMARY KEY);
            INSERT INTO research_graph_instances VALUES ('graph-1');
        """)


def test_cutover_preserves_normal_records_and_removes_graph_state_atomically(tmp_path):
    database = tmp_path / "catalog.sqlite"
    backup = tmp_path / "catalog-before.sqlite"
    graph_files = tmp_path / "FactorTester" / "research-graphs"
    files_backup = tmp_path / "research-graphs-before"
    graph_files.mkdir(parents=True)
    (graph_files / "custom.yaml").write_text("title: old graph\n", encoding="utf-8")
    _create_database(database)

    with sqlite3.connect(database) as conn:
        before = inspect(conn, graph_files=graph_files)
    assert before["graph_tables"]["research_graph_instances"] == 1
    assert before["graph_evidence_admissions"] == 2
    assert before["maintenance_graph_refs"] == {"cases": 1, "refs": 2, "unclassified_rows": 0}
    assert before["graph_files"]["file_count"] == 1
    assert before["preserved"]["research_catalog_reports"]["count"] == 1
    assert before["report_evidence_graph_ref_values"] == 1
    assert before["run_retired_column_values"] == {"graph_instance_id": 1}
    assert before["ready_to_apply"] is True
    assert before["blockers"] == []

    result = apply(
        database,
        backup,
        graph_files=graph_files,
        files_backup=files_backup,
    )

    assert result["after"]["preserved"] == before["preserved"]
    assert result["after"]["graph_tables"] == {}
    assert result["graph_evidence_admissions_removed"] == 2
    assert result["maintenance_graph_refs_removed"] == 2
    assert result["after"]["graph_files"]["state"] == "absent"
    assert not graph_files.exists()
    assert (files_backup / "custom.yaml").read_text(encoding="utf-8") == "title: old graph\n"

    with sqlite3.connect(database) as conn:
        assert "graph_instance_id" not in {
            row[1] for row in conn.execute("PRAGMA table_info(research_runs)")
        }
        assert "graph_ref" not in {
            row[1] for row in conn.execute(
                "PRAGMA table_info(research_catalog_report_evidence_links)"
            )
        }
        assert conn.execute(
            "SELECT content FROM research_catalog_branches WHERE branch_id='main'"
        ).fetchone()[0] == "正文"
        admissions = conn.execute(
            "SELECT admission_ref, subject_ref, note FROM research_evidence_admissions"
        ).fetchall()
        assert admissions == [("admission-report", "report:report-1:main", "keep")]
        case = conn.execute(
            "SELECT affected_refs_json, change_refs_json FROM research_maintenance_cases WHERE case_id='case-1'"
        ).fetchone()
        assert json.loads(case[0]) == ["job:job-1"]
        assert json.loads(case[1]) == ["evidence:evidence-1"]
        assert conn.execute("PRAGMA foreign_key_check").fetchone() is None

    with sqlite3.connect(backup) as conn:
        assert "research_graph_instances" in {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert conn.execute(
            "SELECT COUNT(*) FROM research_evidence_admissions"
        ).fetchone()[0] == 3


def test_cutover_migrates_job_assurance_inside_the_graph_transaction(tmp_path):
    database = tmp_path / "catalog.sqlite"
    backup = tmp_path / "catalog-before.sqlite"
    graph_files = tmp_path / "research-graphs"
    _create_legacy_database(database)
    _insert_job(
        database, job_id="trusted", status="succeeded", with_receipt=True,
    )
    with sqlite3.connect(database) as conn:
        conn.execute(
            "CREATE TABLE research_graph_instances (instance_id TEXT PRIMARY KEY)"
        )
        conn.execute("INSERT INTO research_graph_instances VALUES ('instance-1')")

    result = apply(database, backup, graph_files=graph_files)

    assert result["assurance_migration"]["legacy_receipts_migrated"] == 1
    assert result["assurance_migration"]["legacy_table_dropped"] == 1
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT terminal_assurance_json FROM research_jobs WHERE job_id='trusted'"
        ).fetchone()
        receipt_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='research_backend_assurance_receipts'"
        ).fetchone()
    assert json.loads(row["terminal_assurance_json"])["disposition"] == "trusted"
    assert receipt_table is None


def test_dry_run_reports_unknown_graph_tables_without_mutating(tmp_path):
    database = tmp_path / "catalog.sqlite"
    graph_files = tmp_path / "research-graphs"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE research_graph_future (id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO research_graph_future VALUES ('future-1')")
        before = inspect(conn, graph_files=graph_files)
    assert before["unknown_graph_tables"] == ["research_graph_future"]
    assert before["graph_files"]["state"] == "absent"
    assert before["ready_to_apply"] is False
    assert any("unknown Graph tables" in item for item in before["blockers"])
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM research_graph_future").fetchone()[0] == 1


def test_cutover_refuses_unknown_external_foreign_key_and_keeps_file_tree(tmp_path):
    database = tmp_path / "catalog.sqlite"
    backup = tmp_path / "catalog-before.sqlite"
    graph_files = tmp_path / "research-graphs"
    graph_files.mkdir()
    (graph_files / "graph.yaml").write_text("content\n", encoding="utf-8")
    with sqlite3.connect(database) as conn:
        conn.executescript("""
            CREATE TABLE research_graph_instances (instance_id TEXT PRIMARY KEY);
            CREATE TABLE unrelated (
                id TEXT PRIMARY KEY, graph_instance_id TEXT,
                FOREIGN KEY(graph_instance_id) REFERENCES research_graph_instances(instance_id)
            );
        """)
    with pytest.raises(RuntimeError, match="unknown Graph columns|external foreign keys"):
        apply(database, backup, graph_files=graph_files, files_backup=tmp_path / "files-backup")
    assert graph_files.exists()
    with sqlite3.connect(database) as conn:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_graph_instances'"
        ).fetchone() is not None


def test_cutover_refuses_unclassified_maintenance_graph_reference(tmp_path):
    database = tmp_path / "catalog.sqlite"
    backup = tmp_path / "catalog-before.sqlite"
    graph_files = tmp_path / "research-graphs"
    graph_files.mkdir()
    with sqlite3.connect(database) as conn:
        conn.executescript("""
            CREATE TABLE research_maintenance_cases (
                case_id TEXT PRIMARY KEY, affected_refs_json TEXT NOT NULL,
                change_refs_json TEXT NOT NULL
            );
            INSERT INTO research_maintenance_cases VALUES (
                'case-1', '["graph-future:opaque"]', '[]'
            );
        """)
        report = inspect(conn, graph_files=graph_files)
    assert report["maintenance_graph_refs"]["unclassified_rows"] == 1
    with pytest.raises(RuntimeError, match="manual classification"):
        apply(
            database, backup, graph_files=graph_files,
            files_backup=tmp_path / "files-backup",
        )
    assert not backup.exists()
