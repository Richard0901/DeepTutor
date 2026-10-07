"""Gradebook (Sprint 5): 40/60 framework WITHOUT weight synthesis.

The formative (过程性, 40%) side aggregates teaching records; the summative
(终结性, 60%) side is teacher-entered with full history.  Per plan §2.1 the
final weighted grade is NOT computed here — weights are frozen only after
the D-series decisions sign off, and the output deliberately carries no
combined score field.
"""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
import uuid

from deeptutor.teaching.models import utc_now
from deeptutor.teaching.service import TeachingError, TeachingService

STAFF_ROLES = ("course_admin", "teacher", "reviewer")


def _uuid() -> str:
    return uuid.uuid4().hex


class GradebookService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._teaching = TeachingService(conn)

    def _require_staff(self, class_id: str, actor_id: str) -> None:
        self._teaching.require_role(class_id, actor_id, allowed=STAFF_ROLES)

    def gradebook(self, class_id: str, *, actor_id: str) -> dict:
        self._teaching.get_class(class_id)
        self._require_staff(class_id, actor_id)

        students = [
            dict(r)
            for r in self._conn.execute(
                """
                SELECT m.user_id AS student_id,
                       COUNT(DISTINCT t.attempt_id) AS attempts_total,
                       COUNT(DISTINCT CASE WHEN t.status != 'in_progress' THEN t.attempt_id END)
                           AS attempts_submitted,
                       COUNT(DISTINCT CASE WHEN t.status = 'reviewed' THEN t.attempt_id END)
                           AS attempts_reviewed,
                       SUM(CASE WHEN rs.is_correct = 1 THEN 1 ELSE 0 END) AS marked_correct,
                       SUM(CASE WHEN rs.is_correct IN (0, 1) THEN 1 ELSE 0 END) AS marked_total
                FROM class_memberships m
                LEFT JOIN case_attempts t ON t.student_id = m.user_id
                LEFT JOIN reasoning_steps rs ON rs.attempt_id = t.attempt_id
                WHERE m.class_id = ? AND m.dropped_at IS NULL AND m.role = 'student'
                GROUP BY m.user_id ORDER BY m.user_id
                """,
                (class_id,),
            ).fetchall()
        ]
        titles = [
            r["title"]
            for r in self._conn.execute(
                "SELECT DISTINCT title FROM summative_scores WHERE class_id = ? ORDER BY created_at",
                (class_id,),
            ).fetchall()
        ]
        summative: dict[str, dict[str, float | None]] = {s: {} for s in
                                                          (row["student_id"] for row in students)}
        for row in self._conn.execute(
            """
            SELECT student_id, title, score FROM summative_scores
            WHERE class_id = ?
            ORDER BY created_at
            """,
            (class_id,),
        ).fetchall():
            summative.setdefault(row["student_id"], {})[row["title"]] = row["score"]
        for row in students:
            row["formative"] = {
                "attempts_total": row.pop("attempts_total"),
                "attempts_submitted": row.pop("attempts_submitted"),
                "attempts_reviewed": row.pop("attempts_reviewed"),
                "marked_correct": row.pop("marked_correct") or 0,
                "marked_total": row.pop("marked_total") or 0,
            }
            row["summative"] = summative.get(row["student_id"], {})
        return {
            "class_id": class_id,
            # 40/60 framework placeholder: components only, no weighted total
            # until the D-series decisions freeze the weights (SKILL Sprint 5).
            "framework": {"formative_weight": 0.4, "summative_weight": 0.6, "weighted_total": None},
            "summative_titles": titles,
            "students": students,
        }

    def record_summative_score(
        self,
        class_id: str,
        *,
        teacher_id: str,
        student_id: str,
        title: str,
        score: float,
        note: str = "",
    ) -> dict:
        self._require_staff(class_id, teacher_id)
        membership = self._teaching.get_membership(class_id, student_id)
        if membership is None or membership.role != "student":
            raise TeachingError(f"user '{student_id}' is not a student of class '{class_id}'")
        if not isinstance(score, (int, float)) or not 0 <= score <= 100:
            raise TeachingError("score must be a number between 0 and 100")
        if not title.strip():
            raise TeachingError("score title must not be empty")
        row_id = _uuid()
        self._conn.execute(
            """
            INSERT INTO summative_scores (score_row_id, class_id, student_id, title,
                                          score, teacher_id, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (row_id, class_id, student_id, title.strip(), float(score), teacher_id, note, utc_now()),
        )
        self._conn.commit()
        return {
            "score_row_id": row_id,
            "class_id": class_id,
            "student_id": student_id,
            "title": title.strip(),
            "score": float(score),
            "teacher_id": teacher_id,
            "note": note,
        }

    def csv_export(self, class_id: str, *, actor_id: str) -> str:
        """CSV export of the gradebook frame (no weighted totals)."""
        data = self.gradebook(class_id, actor_id=actor_id)
        titles = data["summative_titles"]
        header = [
            "student_id",
            "attempts_total",
            "attempts_submitted",
            "attempts_reviewed",
            "marked_correct",
            "marked_total",
            *[f"summative:{title}" for title in titles],
        ]
        lines = [",".join(header)]
        for s in data["students"]:
            f = s["formative"]
            cells = [
                s["student_id"],
                str(f["attempts_total"]),
                str(f["attempts_submitted"]),
                str(f["attempts_reviewed"]),
                str(f["marked_correct"]),
                str(f["marked_total"]),
                *[("" if s["summative"].get(title) is None else str(s["summative"][title])) for title in titles],
            ]
            lines.append(",".join(cells))
        return "\n".join(lines) + "\n"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
