"""Assessment service: runs, review workflow, repetition detection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sqlite3
import uuid

from deeptutor.assessment.rules import assess_attempt
from deeptutor.teaching.audit import record_audit
from deeptutor.teaching.models import utc_now
from deeptutor.teaching.service import (
    NotFoundError,
    TeachingError,
    TeachingService,
)


def _uuid() -> str:
    return uuid.uuid4().hex

#: Repetition threshold defaults (D2 draft: 14 days / >=3 confirmed hits).
DEFAULT_REPETITION_WINDOW_DAYS = 14
DEFAULT_REPETITION_THRESHOLD = 3

STAFF_ROLES = ("course_admin", "teacher", "reviewer")


class AssessmentStateError(TeachingError):
    pass


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


class AssessmentService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._teaching = TeachingService(conn)

    # -- helpers -----------------------------------------------------------

    def _attempt_context(self, attempt_id: str) -> tuple[sqlite3.Row, str, str]:
        row = self._conn.execute(
            """
            SELECT t.*, a.class_id AS _class_id, a.case_id AS _case_id
            FROM case_attempts t JOIN assignments a ON a.assignment_id = t.assignment_id
            WHERE t.attempt_id = ?
            """,
            (attempt_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"attempt '{attempt_id}' not found")
        return row, row["_class_id"], row["_case_id"]

    def _require_staff(self, class_id: str, actor_id: str) -> None:
        self._teaching.require_role(class_id, actor_id, allowed=STAFF_ROLES)

    def _case_content(self, case_id: str) -> dict:
        row = self._conn.execute(
            """
            SELECT cv.content_json FROM case_versions cv
            JOIN clinical_cases cc ON cc.current_version_id = cv.version_id
            WHERE cc.case_id = ?
            """,
            (case_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"case '{case_id}' not found")
        return json.loads(row["content_json"])

    def _ensure_rubric(self, case_id: str) -> str:
        """Snapshot the case's scoring rubric as a versioned rubric (idempotent
        per case version)."""
        version = self._conn.execute(
            "SELECT current_version_id FROM clinical_cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        if version is None:
            raise NotFoundError(f"case '{case_id}' not found")
        version_id = version["current_version_id"]
        existing = self._conn.execute(
            "SELECT rubric_id FROM rubric_versions WHERE case_version_id = ?",
            (version_id,),
        ).fetchone()
        if existing is not None:
            return existing["rubric_id"]
        content = self._conn.execute(
            "SELECT content_json FROM case_versions WHERE version_id = ?", (version_id,)
        ).fetchone()["content_json"]
        payload = json.loads(content)
        rubric = payload.get("content", {}).get("scoring_rubric", {})
        rubric_id = _uuid()
        self._conn.execute(
            """
            INSERT INTO rubric_versions (rubric_id, case_id, case_version_id,
                                         rubric_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (rubric_id, case_id, version_id, json.dumps(rubric, ensure_ascii=False), utc_now()),
        )
        self._conn.commit()
        return rubric_id

    # -- running assessments -------------------------------------------------

    def run_assessment(self, attempt_id: str, *, actor_id: str, engine: str = "rules_v1") -> dict:
        if engine != "rules_v1":
            raise TeachingError(
                "only engine='rules_v1' is available; llm_local waits for the G3 validity study"
            )
        attempt, class_id, case_id = self._attempt_context(attempt_id)
        self._require_staff(class_id, actor_id)
        if attempt["status"] == "in_progress":
            raise AssessmentStateError("assessment runs apply to submitted attempts")
        steps = [
            dict(r)
            for r in self._conn.execute(
                "SELECT * FROM reasoning_steps WHERE attempt_id = ? ORDER BY created_at",
                (attempt_id,),
            ).fetchall()
        ]
        if not steps:
            raise AssessmentStateError("the attempt has no reasoning steps to assess")
        content = self._case_content(case_id)["content"]
        rubric_id = self._ensure_rubric(case_id)

        result = assess_attempt(dict(attempt), steps, content)
        run_id = _uuid()
        now = utc_now()
        self._conn.execute(
            """
            INSERT INTO assessment_runs (run_id, attempt_id, rubric_id, engine,
                                         status, summary_json, created_at)
            VALUES (?, ?, ?, ?, 'completed', ?, ?)
            """,
            (run_id, attempt_id, rubric_id, engine, json.dumps(result["summary"], ensure_ascii=False), now),
        )
        record_audit(
            self._conn,
            actor_id=actor_id,
            action="assessment_run",
            object_type="attempt",
            object_id=attempt_id,
            class_id=class_id,
            summary={"engine": engine, "findings": len(result["findings"])},
        )
        for finding in result["findings"]:
            self._conn.execute(
                """
                INSERT INTO assessment_scores (score_id, run_id, step_id, error_type,
                                               confidence, evidence, suggestion,
                                               needs_human_review, review_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'pending', ?)
                """,
                (
                    _uuid(),
                    run_id,
                    finding["step_id"],
                    finding["error_type"],
                    finding["confidence"],
                    finding["evidence"],
                    finding["suggestion"],
                    now,
                ),
            )
        self._conn.commit()
        return self.get_run(run_id, actor_id=actor_id)

    def get_run(self, run_id: str, *, actor_id: str) -> dict:
        run = self._conn.execute(
            "SELECT * FROM assessment_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if run is None:
            raise NotFoundError(f"assessment run '{run_id}' not found")
        _attempt, class_id, _case = self._attempt_context(run["attempt_id"])
        self._require_staff(class_id, actor_id)
        scores = [
            _row_to_dict(r)
            for r in self._conn.execute(
                "SELECT * FROM assessment_scores WHERE run_id = ? ORDER BY created_at",
                (run_id,),
            ).fetchall()
        ]
        return {
            **_row_to_dict(run),
            "summary": json.loads(run["summary_json"]) if run["summary_json"] else None,
            "scores": scores,
        }

    # -- review workflow -------------------------------------------------------

    def review_queue(self, class_id: str, *, actor_id: str) -> list[dict]:
        """Pending first-pass findings for the teacher's class."""
        self._require_staff(class_id, actor_id)
        rows = self._conn.execute(
            """
            SELECT s.*, t.student_id AS student_id, a.class_id AS class_id
            FROM assessment_scores s
            JOIN assessment_runs r ON r.run_id = s.run_id
            JOIN case_attempts t ON t.attempt_id = r.attempt_id
            JOIN assignments a ON a.assignment_id = t.assignment_id
            WHERE a.class_id = ? AND s.review_status = 'pending'
            ORDER BY s.created_at
            """,
            (class_id,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def record_review(
        self,
        score_id: str,
        *,
        teacher_id: str,
        action: str,
        final_error_type: str | None = None,
        final_is_correct: bool | None = None,
        comment: str = "",
    ) -> dict:
        if action not in ("agree", "override", "dismiss"):
            raise TeachingError(f"unknown review action '{action}'")
        score = self._conn.execute(
            "SELECT * FROM assessment_scores WHERE score_id = ?", (score_id,)
        ).fetchone()
        if score is None:
            raise NotFoundError(f"assessment score '{score_id}' not found")
        run = self._conn.execute(
            "SELECT attempt_id FROM assessment_runs WHERE run_id = ?", (score["run_id"],)
        ).fetchone()
        _attempt, class_id, _case = self._attempt_context(run["attempt_id"])
        self._require_staff(class_id, teacher_id)
        if score["review_status"] != "pending":
            raise AssessmentStateError(
                f"score '{score_id}' is '{score['review_status']}'; already reviewed"
            )
        if action == "override" and final_error_type is None and final_is_correct is None:
            raise TeachingError("override requires final_error_type or final_is_correct")
        review_id = _uuid()
        now = utc_now()
        self._conn.execute(
            """
            INSERT INTO human_reviews (review_id, score_id, teacher_id, action,
                                       final_error_type, final_is_correct, comment, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                score_id,
                teacher_id,
                action,
                final_error_type,
                None if final_is_correct is None else (1 if final_is_correct else 0),
                comment,
                now,
            ),
        )
        status_map = {"agree": "agreed", "override": "overridden", "dismiss": "dismissed"}
        self._conn.execute(
            "UPDATE assessment_scores SET review_status = ? WHERE score_id = ?",
            (status_map[action], score_id),
        )
        record_audit(
            self._conn,
            actor_id=teacher_id,
            action="assessment_review",
            object_type="assessment_score",
            object_id=score_id,
            class_id=class_id,
            summary={"action": action, "final_error_type": final_error_type},
        )
        self._conn.commit()
        return {
            "review_id": review_id,
            "score_id": score_id,
            "action": action,
            "final_error_type": final_error_type,
            "final_is_correct": final_is_correct,
            "comment": comment,
        }

    # -- repetition detection (D2 draft thresholds) ----------------------------

    def error_repetition(
        self,
        student_id: str,
        *,
        window_days: int = DEFAULT_REPETITION_WINDOW_DAYS,
        threshold: int = DEFAULT_REPETITION_THRESHOLD,
    ) -> dict:
        """Count teacher-confirmed error tags per type inside the window and
        flag which types crossed the systematic-compensation threshold.

        Only confirmed reviews count (agreed/overridden); the final error
        type of an override replaces the AI suggestion.
        """
        since = (
            datetime.now(timezone.utc) - timedelta(days=window_days)
        ).isoformat(timespec="seconds")
        rows = self._conn.execute(
            """
            SELECT COALESCE(h.final_error_type, s.error_type) AS error_type, COUNT(*) AS hits
            FROM human_reviews h
            JOIN assessment_scores s ON s.score_id = h.score_id
            JOIN assessment_runs r ON r.run_id = s.run_id
            JOIN case_attempts t ON t.attempt_id = r.attempt_id
            WHERE t.student_id = ? AND h.created_at >= ?
              AND h.action IN ('agree', 'override')
            GROUP BY error_type
            """,
            (student_id, since),
        ).fetchall()
        counts = {row["error_type"]: row["hits"] for row in rows if row["error_type"]}
        return {
            "student_id": student_id,
            "window_days": window_days,
            "threshold": threshold,
            "confirmed_counts": counts,
            "compensation_triggered": sorted(
                error_type for error_type, hits in counts.items() if hits >= threshold
            ),
        }
