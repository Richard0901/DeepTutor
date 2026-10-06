"""Central teaching database: connection handling and schema migrations.

The teaching domain keeps its own SQLite database (default
``<runtime-home>/data/system/clinical_learning.db``) with WAL journaling and
foreign keys enforced.  Migrations are plain ordered (version, name, up,
down) entries recorded in ``_teaching_schema_migrations``; applying them is
idempotent and ``rollback`` supports dropping back to an earlier revision.

Override the database location with the ``DEEPTUTOR_TEACHING_DB`` environment
variable (tests use this to point at a temporary file).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sqlite3

from deeptutor.teaching.migrations import MIGRATIONS, Migration

logger = logging.getLogger(__name__)

_MIGRATIONS_TABLE = "_teaching_schema_migrations"


def default_db_path() -> Path:
    override = os.environ.get("DEEPTUTOR_TEACHING_DB")
    if override:
        return Path(override)
    # Imported lazily: pulls the runtime-home resolution only when the
    # default location is actually needed.
    from deeptutor.multi_user.paths import SYSTEM_ROOT

    return Path(SYSTEM_ROOT) / "clinical_learning.db"


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open the teaching database with the domain's standard pragmas."""
    path = Path(db_path) if db_path is not None else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def applied_versions(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_MIGRATIONS_TABLE} (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    rows = conn.execute(
        f"SELECT version, name FROM {_MIGRATIONS_TABLE} ORDER BY version"
    ).fetchall()
    return [(int(row["version"]), str(row["name"])) for row in rows]


def migrate(conn: sqlite3.Connection, target: int | None = None) -> list[tuple[int, str]]:
    """Apply pending migrations in order. Returns newly applied entries."""
    applied_versions(conn)  # ensure the bookkeeping table exists
    current = conn.execute(f"SELECT COALESCE(MAX(version), 0) FROM {_MIGRATIONS_TABLE}").fetchone()[0]
    applied: list[tuple[int, str]] = []
    for migration in MIGRATIONS:
        if migration.version <= current:
            continue
        if target is not None and migration.version > target:
            break
        logger.info("applying teaching migration %03d_%s", migration.version, migration.name)
        conn.executescript(migration.up)
        conn.execute(
            f"INSERT INTO {_MIGRATIONS_TABLE} (version, name) VALUES (?, ?)",
            (migration.version, migration.name),
        )
        applied.append((migration.version, migration.name))
    conn.commit()
    return applied


def rollback(conn: sqlite3.Connection, target: int = 0) -> list[int]:
    """Revert applied migrations down to (excluding) ``target``, newest first."""
    applied_versions(conn)
    current = conn.execute(f"SELECT COALESCE(MAX(version), 0) FROM {_MIGRATIONS_TABLE}").fetchone()[0]
    reverted: list[int] = []
    for migration in reversed(MIGRATIONS):
        if migration.version <= target or migration.version > current:
            continue
        logger.info("reverting teaching migration %03d_%s", migration.version, migration.name)
        conn.executescript(migration.down)
        conn.execute(f"DELETE FROM {_MIGRATIONS_TABLE} WHERE version = ?", (migration.version,))
        reverted.append(migration.version)
    conn.commit()
    return reverted


def known_migrations() -> list[Migration]:
    return list(MIGRATIONS)
