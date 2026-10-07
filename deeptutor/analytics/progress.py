"""Student self-progress profile (Sprint 5): teaching-domain aggregates only.

Level distribution, teacher-confirmed error trends and triggered
compensations are computed from the teaching database; Mastery Path
learning data is deliberately not mixed in.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

from deeptutor.assessment.service import (
    DEFAULT_REPETITION_THRESHOLD,
    DEFAULT_REPETITION_WINDOW_DAYS,
)


def my_progress(conn: sqlite3.Connection, student_id: str) -> dict:
    levels = [
        dict(r)
        for r in conn.execute(
            """
            SELECT c.level AS level,
                   COUNT(DISTINCT t.attempt_id) AS attempts,
                   COUNT(DISTINCT CASE WHEN t.status != 'in_progress' THEN t.attempt_id END)
                       AS submitted,
                   COUNT(DISTINCT CASE WHEN t.status = 'reviewed' THEN t.attempt_id END)
                       AS reviewed
            FROM case_attempts t
            JOIN assignments a ON a.assignment_id = t.assignment_id
            JOIN clinical_cases c ON c.case_id = a.case_id
            WHERE t.student_id = ?
            GROUP BY c.level
            """,
            (student_id,),
        ).fetchall()
    ]
    distribution = {
        row["level"]: {
            "attempts": row["attempts"],
            "submitted": row["submitted"],
            "reviewed": row["reviewed"],
        }
        for row in levels
    }

    since = (
        datetime.now(timezone.utc) - timedelta(days=30)
    ).isoformat(timespec="seconds")
    confirmed = [
        dict(r)
        for r in conn.execute(
            """
            SELECT COALESCE(h.final_error_type, s.error_type) AS error_type,
                   COUNT(*) AS hits,
                   MAX(h.created_at) AS last_confirmed_at
            FROM human_reviews h
            JOIN assessment_scores s ON s.score_id = h.score_id
            JOIN assessment_runs r ON r.run_id = s.run_id
            JOIN case_attempts t ON t.attempt_id = r.attempt_id
            WHERE t.student_id = ? AND h.action IN ('agree', 'override')
            GROUP BY error_type
            """,
            (student_id,),
        ).fetchall()
    ]
    error_trends = {
        row["error_type"]: {
            "total": row["hits"],
            "last_30d": (
                conn.execute(
                    """
                    SELECT COUNT(*) FROM human_reviews h
                    JOIN assessment_scores s ON s.score_id = h.score_id
                    JOIN assessment_runs r ON r.run_id = s.run_id
                    JOIN case_attempts t ON t.attempt_id = r.attempt_id
                    WHERE t.student_id = ? AND h.action IN ('agree', 'override')
                      AND COALESCE(h.final_error_type, s.error_type) = ?
                      AND h.created_at >= ?
                    """,
                    (student_id, row["error_type"], since),
                ).fetchone()[0]
            ),
        }
        for row in confirmed
        if row["error_type"]
    }

    from deeptutor.assessment.service import AssessmentService

    repetition = AssessmentService(conn).error_repetition(
        student_id,
        window_days=DEFAULT_REPETITION_WINDOW_DAYS,
        threshold=DEFAULT_REPETITION_THRESHOLD,
    )

    return {
        "student_id": student_id,
        "level_distribution": distribution,
        "error_trends": error_trends,
        "compensation_triggered": repetition["compensation_triggered"],
        "compensation_window_days": DEFAULT_REPETITION_WINDOW_DAYS,
        "compensation_threshold": DEFAULT_REPETITION_THRESHOLD,
    }
