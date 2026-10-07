"""Teaching-domain audit trail (Sprint 5 governance).

Records are inserted in the SAME transaction as the action they describe —
unlike the upstream best-effort usage JSONL — so a committed action always
has its audit row.  Summaries carry action/object/actor metadata only:
case text, reasoning content and other sensitive payloads never enter the
audit table.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any
import uuid

from deeptutor.teaching.models import utc_now
from deeptutor.teaching.service import TeachingService


def _uuid() -> str:
    return uuid.uuid4().hex


def record_audit(
    conn: sqlite3.Connection,
    *,
    actor_id: str,
    action: str,
    object_type: str,
    object_id: str,
    class_id: str | None = None,
    summary: dict[str, Any] | None = None,
) -> None:
    """Insert one audit row inside the caller's open transaction."""
    conn.execute(
        """
        INSERT INTO teaching_audit_events (audit_id, created_at, actor_id, action,
                                           object_type, object_id, class_id, summary_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _uuid(),
            utc_now(),
            actor_id,
            action,
            object_type,
            object_id,
            class_id,
            json.dumps(summary or {}, ensure_ascii=False),
        ),
    )


def query_audit(
    conn: sqlite3.Connection,
    *,
    class_id: str | None = None,
    action: str | None = None,
    actor_id: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Read-only audit query; authorization is enforced by callers."""
    sql = "SELECT * FROM teaching_audit_events WHERE 1=1"
    params: list[Any] = []
    if class_id is not None:
        sql += " AND class_id = ?"
        params.append(class_id)
    if action is not None:
        sql += " AND action = ?"
        params.append(action)
    if actor_id is not None:
        sql += " AND actor_id = ?"
        params.append(actor_id)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def require_class_staff(conn: sqlite3.Connection, class_id: str, actor_id: str) -> None:
    TeachingService(conn).require_role(
        class_id, actor_id, allowed=("course_admin", "teacher", "reviewer")
    )
