"""Teacher analytics (plan WP8, minimal): class overview, deterministic risk
flags and the intervention loop.

Everything here is computed from persisted records — no LLM in the truth
path (plan §5.2: 看板由确定性 analytics 服务承载，LLM 仅生成摘要). Risk
rules are transparent and listed with their evidence; a persisted
risk_flags/analytics_snapshots table is deferred (see migration 0006).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
import uuid

from deeptutor.teaching.audit import record_audit
from deeptutor.teaching.models import utc_now
from deeptutor.teaching.service import NotFoundError, TeachingError, TeachingService

STAFF_ROLES = ("course_admin", "teacher", "reviewer")

#: Risk rule parameters (transparent, versioned with the code until D2/D6
#: decisions finalize formal thresholds).
STALE_IN_PROGRESS_DAYS = 7


def _uuid() -> str:
    return uuid.uuid4().hex


class AnalyticsService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._teaching = TeachingService(conn)

    def _require_staff(self, class_id: str, actor_id: str) -> None:
        self._teaching.require_role(class_id, actor_id, allowed=STAFF_ROLES)

    def _class_exists(self, class_id: str) -> None:
        try:
            self._teaching.get_class(class_id)
        except Exception:
            raise NotFoundError(f"class '{class_id}' not found") from None

    # -- overview ----------------------------------------------------------

    def class_overview(self, class_id: str, *, actor_id: str) -> dict:
        self._class_exists(class_id)
        self._require_staff(class_id, actor_id)

        assignments = [
            dict(r)
            for r in self._conn.execute(
                """
                SELECT a.assignment_id, a.title, a.status, a.case_id,
                       (SELECT COUNT(*) FROM case_attempts t
                         WHERE t.assignment_id = a.assignment_id) AS attempts_total,
                       (SELECT COUNT(DISTINCT t.student_id) FROM case_attempts t
                         WHERE t.assignment_id = a.assignment_id) AS students_started
                FROM assignments a WHERE a.class_id = ? ORDER BY a.created_at
                """,
                (class_id,),
            ).fetchall()
        ]
        students = self._student_rows(class_id)
        return {
            "class_id": class_id,
            "assignments": assignments,
            "students": students,
            "pending_reviews": self._conn.execute(
                "SELECT COUNT(*) FROM assessment_scores s"
                " JOIN assessment_runs r ON r.run_id = s.run_id"
                " JOIN case_attempts t ON t.attempt_id = r.attempt_id"
                " JOIN assignments a ON a.assignment_id = t.assignment_id"
                " WHERE a.class_id = ? AND s.review_status = 'pending'",
                (class_id,),
            ).fetchone()[0],
            "open_interventions": self._conn.execute(
                "SELECT COUNT(*) FROM teacher_interventions WHERE class_id = ? AND status = 'open'",
                (class_id,),
            ).fetchone()[0],
        }

    def _student_rows(self, class_id: str) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT m.user_id AS student_id, m.role,
                   COUNT(DISTINCT t.attempt_id) AS attempts_total,
                   COUNT(DISTINCT CASE WHEN t.status != 'in_progress' THEN t.attempt_id END) AS attempts_submitted,
                   COUNT(DISTINCT CASE WHEN t.status = 'reviewed' THEN t.attempt_id END) AS attempts_reviewed,
                   MAX(COALESCE(t.submitted_at, t.started_at)) AS last_activity_at
            FROM class_memberships m
            LEFT JOIN case_attempts t ON t.student_id = m.user_id
            WHERE m.class_id = ? AND m.dropped_at IS NULL AND m.role = 'student'
            GROUP BY m.user_id ORDER BY m.user_id
            """,
            (class_id,),
        ).fetchall()
        students = []
        for row in rows:
            student = dict(row)
            student["confirmed_errors"] = self._confirmed_errors(student["student_id"])
            students.append(student)
        return students

    def _confirmed_errors(self, student_id: str) -> dict[str, int]:
        rows = self._conn.execute(
            """
            SELECT COALESCE(h.final_error_type, s.error_type) AS error_type, COUNT(*) AS hits
            FROM human_reviews h
            JOIN assessment_scores s ON s.score_id = h.score_id
            JOIN assessment_runs r ON r.run_id = s.run_id
            JOIN case_attempts t ON t.attempt_id = r.attempt_id
            WHERE t.student_id = ? AND h.action IN ('agree', 'override')
            GROUP BY error_type
            """,
            (student_id,),
        ).fetchall()
        return {row["error_type"]: row["hits"] for row in rows if row["error_type"]}

    # -- risk flags ----------------------------------------------------------

    def risk_flags(self, class_id: str, *, actor_id: str) -> list[dict]:
        """Deterministic per-student risk list with transparent evidence."""
        self._class_exists(class_id)
        self._require_staff(class_id, actor_id)
        stale_cutoff = (
            datetime.now(timezone.utc) - timedelta(days=STALE_IN_PROGRESS_DAYS)
        ).isoformat(timespec="seconds")
        flags: list[dict] = []
        for student in self._student_rows(class_id):
            sid = student["student_id"]
            reasons: list[str] = []
            if student["attempts_total"] == 0:
                reasons.append("no_attempts")
            if student["attempts_submitted"] > 0 and student["attempts_reviewed"] == 0:
                reasons.append("no_reviewed_attempts")
            stale = self._conn.execute(
                """
                SELECT t.attempt_id, t.started_at FROM case_attempts t
                JOIN assignments a ON a.assignment_id = t.assignment_id
                WHERE a.class_id = ? AND t.student_id = ? AND t.status = 'in_progress'
                  AND t.started_at <= ?
                """,
                (class_id, sid, stale_cutoff),
            ).fetchall()
            if stale:
                reasons.append(f"stale_in_progress(>{STALE_IN_PROGRESS_DAYS}d): " + ",".join(
                    r["attempt_id"][:8] for r in stale
                ))
            triggered = sorted(
                error_type for error_type, hits in student["confirmed_errors"].items() if hits >= 3
            )
            if triggered:
                reasons.append("error_repetition: " + ",".join(triggered))
            if reasons:
                flags.append(
                    {
                        "student_id": sid,
                        "reasons": reasons,
                        "confirmed_errors": student["confirmed_errors"],
                        "attempts_total": student["attempts_total"],
                        "attempts_submitted": student["attempts_submitted"],
                        "last_activity_at": student["last_activity_at"],
                    }
                )
        return flags

    # -- interventions ---------------------------------------------------------

    def record_intervention(
        self,
        class_id: str,
        *,
        teacher_id: str,
        student_id: str,
        reason: str,
        note: str = "",
    ) -> dict:
        self._require_staff(class_id, teacher_id)
        membership = self._teaching.get_membership(class_id, student_id)
        if membership is None or membership.role != "student":
            raise TeachingError(
                f"user '{student_id}' is not a student of class '{class_id}'"
            )
        if not reason.strip():
            raise TeachingError("intervention reason must not be empty")
        intervention_id = _uuid()
        self._conn.execute(
            """
            INSERT INTO teacher_interventions (intervention_id, class_id, student_id,
                                               teacher_id, reason, note, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'open', ?)
            """,
            (intervention_id, class_id, student_id, teacher_id, reason.strip(), note, utc_now()),
        )
        record_audit(
            self._conn,
            actor_id=teacher_id,
            action="intervention_record",
            object_type="intervention",
            object_id=intervention_id,
            class_id=class_id,
            summary={"student_id": student_id},
        )
        self._conn.commit()
        return self.get_intervention(intervention_id, actor_id=teacher_id)

    def resolve_intervention(
        self, intervention_id: str, *, actor_id: str, outcome: str = ""
    ) -> dict:
        row = self._get_intervention_raw(intervention_id)
        self._require_staff(row["class_id"], actor_id)
        if row["status"] != "open":
            raise TeachingError(f"intervention '{intervention_id}' is already '{row['status']}'")
        self._conn.execute(
            "UPDATE teacher_interventions SET status = 'resolved', outcome = ?, resolved_at = ?"
            " WHERE intervention_id = ?",
            (outcome, utc_now(), intervention_id),
        )
        record_audit(
            self._conn,
            actor_id=actor_id,
            action="intervention_resolve",
            object_type="intervention",
            object_id=intervention_id,
            class_id=row["class_id"],
        )
        self._conn.commit()
        return self.get_intervention(intervention_id, actor_id=actor_id)

    def _get_intervention_raw(self, intervention_id: str) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM teacher_interventions WHERE intervention_id = ?", (intervention_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"intervention '{intervention_id}' not found")
        return row

    def get_intervention(self, intervention_id: str, *, actor_id: str) -> dict:
        row = self._get_intervention_raw(intervention_id)
        self._require_staff(row["class_id"], actor_id)
        return dict(row)

    def list_interventions(self, class_id: str, *, actor_id: str) -> list[dict]:
        self._require_staff(class_id, actor_id)
        rows = self._conn.execute(
            "SELECT * FROM teacher_interventions WHERE class_id = ? ORDER BY created_at DESC",
            (class_id,),
        ).fetchall()
        return [dict(r) for r in rows]
