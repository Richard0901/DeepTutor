#!/usr/bin/env python3
"""Backup the central teaching database (WAL-safe) plus the audit trail.

    python scripts/backup_teaching_db.py [--target DIR] [--keep N]

Uses SQLite's online backup API — with WAL journaling a plain file copy can
miss or corrupt recent commits, so copying ``.db`` files directly is not a
backup.  Also archives the upstream audit JSONL when present.  Default
target: ``<runtime-home>/data/system/backups`` (kept out of git by the
data/ ignore rules); ``--keep`` prunes old archives (default 7).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from deeptutor.teaching.database import default_db_path  # noqa: E402


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _prune(directory: Path, prefix: str, keep: int) -> int:
    archives = sorted(directory.glob(f"{prefix}-*.db"), reverse=True)
    removed = 0
    for old in archives[keep:]:
        old.unlink()
        removed += 1
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        type=Path,
        default=None,
        help="backup directory (default: <runtime-home>/data/system/backups)",
    )
    parser.add_argument("--keep", type=int, default=7, help="number of archives to retain")
    args = parser.parse_args()

    source = default_db_path()
    if not source.exists():
        print(f"teaching database not found at {source}", file=sys.stderr)
        return 1
    target_dir = args.target or (source.parent / "backups")
    target_dir.mkdir(parents=True, exist_ok=True)

    stamp = _utc_stamp()
    archive = target_dir / f"clinical_learning-{stamp}.db"

    started = time.monotonic()
    src_conn = sqlite3.connect(source)
    dst_conn = sqlite3.connect(archive)
    try:
        src_conn.backup(dst_conn)
        # WAL-safe backup via the SQLite online backup API; integrity check
        # on the archive proves the copy is a consistent database.
        result = dst_conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        dst_conn.close()
        src_conn.close()
    elapsed = time.monotonic() - started
    if result != "ok":
        archive.unlink(missing_ok=True)
        print(f"backup FAILED integrity check ({result}); archive removed", file=sys.stderr)
        return 2

    size_mb = archive.stat().st_size / (1024 * 1024)
    print(f"backup ok: {archive} ({size_mb:.1f} MB, {elapsed:.2f}s, integrity ok)")

    # Archive the upstream usage audit trail when present (best-effort copy).
    from deeptutor.multi_user.paths import SYSTEM_ROOT

    usage = Path(SYSTEM_ROOT) / "audit" / "usage.jsonl"
    if usage.exists():
        audit_copy = target_dir / f"usage-audit-{stamp}.jsonl"
        shutil.copy2(usage, audit_copy)
        print(f"audit trail copied: {audit_copy}")

    removed = _prune(target_dir, "clinical_learning", max(1, args.keep))
    if removed:
        print(f"pruned {removed} old archive(s), keeping {args.keep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
