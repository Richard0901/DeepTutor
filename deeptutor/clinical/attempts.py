"""Student case attempts and structured reasoning trails (plan WP4).

The student workflow: receive an assignment → open an attempt → record
structured reasoning steps (append-only) → submit → teacher review.  Steps
are never rewritten once the attempt is submitted, and every action stays
replayable (plan hard constraint #5).

Required step types before submission mirror the 申报书's structured
reasoning fields: 问题表征, 鉴别诊断, 关键证据, 检查选择, 处置方案.
Reassessment (再评估) is optional at submission time.
"""

from __future__ import annotations

import sqlite3
import uuid

from deeptutor.teaching.models import CaseAttempt, ReasoningStep, utc_now
from deeptutor.teaching.service import (
    NotFoundError,
    PermissionDeniedError,
    TeachingError,
    TeachingService,
)

REQUIRED_STEP_TYPES: tuple[str, ...] = (
    "problem_presentation",
    "differential_diagnosis",
    "key_evidence",
    "investigation",
    "disposition",
)
OPTIONAL_STEP_TYPES: tuple[str, ...] = ("reassessment",)
STEP_TYPES: tuple[str, ...] = REQUIRED_STEP_TYPES + OPTIONAL_STEP_TYPES
CLASS_STAFF_ROLES: tuple[str, ...] = ("course_admin", "teacher")


def _uuid() -> str:
    return uuid.uuid4().hex


class AttemptStateError(TeachingError):
    """Raised when an attempt lifecycle transition is not allowed."""


def _row_to_attempt(row: sqlite3.Row) -> CaseAttempt:
    return CaseAttempt(**dict(row))


def _row_to_step(row: sqlite3.Row) -> ReasoningStep:
    return ReasoningStep(**dict(row))


class AttemptService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._teaching = TeachingService(conn)

    # -- reads ------------------------------------------------------------

    def get_attempt(self, attempt_id: str, *, actor_id: str) -> CaseAttempt:
        attempt = self._get_attempt_raw(attempt_id)
        if not self._can_view(attempt, actor_id):
            # Do not reveal attempt existence to unrelated users.
            raise NotFoundError(f"attempt '{attempt_id}' not found")
        return attempt

    def _get_attempt_raw(self, attempt_id: str) -> CaseAttempt:
        row = self._conn.execute(
            "SELECT * FROM case_attempts WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"attempt '{attempt_id}' not found")
        return _row_to_attempt(row)

    def _assignment_class_id(self, assignment_id: str) -> str:
        row = self._conn.execute(
            "SELECT class_id FROM assignments WHERE assignment_id = ?", (assignment_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"assignment '{assignment_id}' not found")
        return row["class_id"]

    def _can_view(self, attempt: CaseAttempt, actor_id: str) -> bool:
        if attempt.student_id == actor_id:
            return True
        class_id = self._assignment_class_id(attempt.assignment_id)
        membership = self._teaching.get_membership(class_id, actor_id)
        return membership is not None and membership.role in (
            *CLASS_STAFF_ROLES,
            "reviewer",
        )

    def list_steps(self, attempt_id: str, *, actor_id: str) -> list[ReasoningStep]:
        self.get_attempt(attempt_id, actor_id=actor_id)
        rows = self._conn.execute(
            "SELECT * FROM reasoning_steps WHERE attempt_id = ? ORDER BY created_at, step_id",
            (attempt_id,),
        ).fetchall()
        return [_row_to_step(row) for row in rows]

    def list_attempts_for_assignment(
        self, assignment_id: str, *, actor_id: str
    ) -> list[CaseAttempt]:
        """Students see their own attempts; class staff see the whole class."""
        class_id = self._assignment_class_id(assignment_id)
        membership = self._teaching.get_membership(class_id, actor_id)
        is_staff = membership is not None and membership.role in (*CLASS_STAFF_ROLES, "reviewer")
        if is_staff:
            rows = self._conn.execute(
                "SELECT * FROM case_attempts WHERE assignment_id = ? ORDER BY started_at",
                (assignment_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM case_attempts WHERE assignment_id = ? AND student_id = ? ORDER BY started_at",
                (assignment_id, actor_id),
            ).fetchall()
        return [_row_to_attempt(row) for row in rows]

    # -- student workflow ---------------------------------------------------

    def create_attempt(self, assignment_id: str, *, student_id: str) -> CaseAttempt:
        row = self._conn.execute(
            "SELECT * FROM assignments WHERE assignment_id = ?", (assignment_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"assignment '{assignment_id}' not found")
        if row["status"] != "open":
            raise AttemptStateError(f"assignment '{assignment_id}' is '{row['status']}', not open")
        case = self._conn.execute(
            "SELECT status FROM clinical_cases WHERE case_id = ?", (row["case_id"],)
        ).fetchone()
        if case is None or case["status"] != "published":
            # Defensive re-check: assignment creation already enforces this,
            # but a case can retire while an assignment stays open.
            raise AttemptStateError("the assigned case is no longer published")
        membership = self._teaching.get_membership(row["class_id"], student_id)
        if membership is None or membership.role != "student":
            raise PermissionDeniedError(
                f"user '{student_id}' is not a student of the assignment's class"
            )
        attempt_id = _uuid()
        now = utc_now()
        self._conn.execute(
            """
            INSERT INTO case_attempts (attempt_id, assignment_id, student_id,
                                       status, started_at, created_at)
            VALUES (?, ?, ?, 'in_progress', ?, ?)
            """,
            (attempt_id, assignment_id, student_id, now, now),
        )
        self._conn.commit()
        return self._get_attempt_raw(attempt_id)

    def add_step(
        self,
        attempt_id: str,
        *,
        actor_id: str,
        step_type: str,
        content: str,
    ) -> ReasoningStep:
        attempt = self._get_attempt_raw(attempt_id)
        if attempt.student_id != actor_id:
            raise PermissionDeniedError("only the attempt owner can record reasoning steps")
        if attempt.status != "in_progress":
            raise AttemptStateError(
                f"attempt '{attempt_id}' is '{attempt.status}'; submitted attempts are locked"
            )
        if step_type not in STEP_TYPES:
            raise TeachingError(f"unknown step type '{step_type}'")
        if not isinstance(content, str) or not content.strip():
            raise TeachingError("step content must be a non-empty string")
        step_id = _uuid()
        now = utc_now()
        self._conn.execute(
            """
            INSERT INTO reasoning_steps (step_id, attempt_id, step_type, content,
                                         created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (step_id, attempt_id, step_type, content.strip(), now, now),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT * FROM reasoning_steps WHERE step_id = ?", (step_id,)
        ).fetchone()
        return _row_to_step(row)

    def submit(self, attempt_id: str, *, actor_id: str) -> CaseAttempt:
        attempt = self._get_attempt_raw(attempt_id)
        if attempt.student_id != actor_id:
            raise PermissionDeniedError("only the attempt owner can submit")
        if attempt.status != "in_progress":
            raise AttemptStateError(f"attempt '{attempt_id}' is '{attempt.status}'")
        present = {
            row["step_type"]
            for row in self._conn.execute(
                "SELECT DISTINCT step_type FROM reasoning_steps WHERE attempt_id = ?",
                (attempt_id,),
            )
        }
        missing = [t for t in REQUIRED_STEP_TYPES if t not in present]
        if missing:
            raise AttemptStateError(
                "cannot submit: missing required reasoning steps: " + ", ".join(missing)
            )
        self._conn.execute(
            "UPDATE case_attempts SET status = 'submitted', submitted_at = ? WHERE attempt_id = ?",
            (utc_now(), attempt_id),
        )
        self._conn.commit()
        return self._get_attempt_raw(attempt_id)

    # -- teacher review -----------------------------------------------------

    def record_review(
        self,
        attempt_id: str,
        *,
        reviewer_id: str,
        notes: str = "",
        step_marks: list[dict] | None = None,
    ) -> CaseAttempt:
        """Review a submitted attempt.

        ``step_marks`` is an optional list of ``{"step_id", "is_correct",
        "comment"}`` dicts applied to the attempt's reasoning steps.
        """
        attempt = self._get_attempt_raw(attempt_id)
        class_id = self._assignment_class_id(attempt.assignment_id)
        self._teaching.require_role(class_id, reviewer_id, allowed=CLASS_STAFF_ROLES)
        if attempt.status != "submitted":
            raise AttemptStateError(
                f"attempt '{attempt_id}' is '{attempt.status}'; only submitted attempts can be reviewed"
            )
        for mark in step_marks or []:
            step_id = mark.get("step_id")
            row = self._conn.execute(
                "SELECT attempt_id FROM reasoning_steps WHERE step_id = ?", (step_id,)
            ).fetchone()
            if row is None or row["attempt_id"] != attempt_id:
                raise NotFoundError(f"step '{step_id}' not found in attempt '{attempt_id}'")
            is_correct = mark.get("is_correct")
            if not isinstance(is_correct, bool):
                raise TeachingError("step_marks.is_correct must be a boolean")
            self._conn.execute(
                """
                UPDATE reasoning_steps
                SET is_correct = ?, teacher_override = ?, reviewed_by_teacher = 1,
                    updated_at = ?
                WHERE step_id = ?
                """,
                (1 if is_correct else 0, str(mark.get("comment", "")), utc_now(), step_id),
            )
        self._conn.execute(
            """
            UPDATE case_attempts
            SET status = 'reviewed', reviewed_at = ?, reviewer_id = ?, review_notes = ?
            WHERE attempt_id = ?
            """,
            (utc_now(), reviewer_id, notes, attempt_id),
        )
        self._conn.commit()
        return self._get_attempt_raw(attempt_id)
