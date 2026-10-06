"""Migration runner tests for the central teaching database."""

from __future__ import annotations

import sqlite3

import pytest

from deeptutor.teaching.database import applied_versions, connect, migrate, rollback
from deeptutor.teaching.migrations import MIGRATIONS


@pytest.fixture()
def conn(tmp_path):
    connection = connect(tmp_path / "teaching.db")
    yield connection
    connection.close()


def test_migrate_applies_all_migrations(conn):
    applied = migrate(conn)
    assert [v for v, _name in applied] == [m.version for m in MIGRATIONS]
    assert applied_versions(conn) == applied


def test_migrate_is_idempotent(conn):
    first = migrate(conn)
    second = migrate(conn)
    assert first and not second


def test_migrate_target_stops_early(conn):
    applied = migrate(conn, target=1)
    assert [v for v, _name in applied] == [1]
    conn.execute(
        "INSERT INTO tenants (tenant_id, name, created_at, updated_at) VALUES ('t1', '一院', 'now', 'now')"
    )
    conn.commit()
    migrate(conn)  # remaining migration applies cleanly on top of data
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"tenants", "courses", "teaching_classes", "class_memberships"} <= tables
    assert "clinical_cases" in tables
    assert "assignments" in tables


def test_rollback_drops_domain_tables(conn):
    migrate(conn)
    rollback(conn, target=0)
    tables = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "tenants" not in tables
    assert "clinical_cases" not in tables
    assert applied_versions(conn) == []
    # A rollback followed by migrate yields a usable database again.
    assert migrate(conn)


def test_wal_and_foreign_keys_enabled(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_case_status_check_constraints(conn):
    migrate(conn)
    conn.execute(
        "INSERT INTO tenants (tenant_id, name, created_at, updated_at) VALUES ('t1', 'x', 'now', 'now')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO clinical_cases (case_id, tenant_id, case_code, title, level,
                                        dimension_complexity, dimension_diagnostic,
                                        dimension_decision, dimension_situational,
                                        created_by, created_at, updated_at)
            VALUES ('c1', 't1', 'RESP-L9-001', 'bad', 'L9', 1, 1, 1, 1, 'a', 'now', 'now')
            """
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO clinical_cases (case_id, tenant_id, case_code, title, level,
                                        dimension_complexity, dimension_diagnostic,
                                        dimension_decision, dimension_situational,
                                        created_by, created_at, updated_at)
            VALUES ('c1', 't1', 'RESP-L1-099', 'bad dims', 'L1', 9, 1, 1, 1, 'a', 'now', 'now')
            """
        )
