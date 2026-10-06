"""Teacher analytics tests (WP8 minimal): overview, risk rules, interventions."""

from __future__ import annotations

import pytest

from deeptutor.analytics.service import STALE_IN_PROGRESS_DAYS, AnalyticsService
from deeptutor.clinical.attempts import REQUIRED_STEP_TYPES, AttemptService
from deeptutor.clinical.case_import import case_template
from deeptutor.clinical.service import ClinicalCaseService
from deeptutor.teaching.database import connect, migrate
from deeptutor.teaching.models import utc_now
from deeptutor.teaching.service import (
    NotFoundError,
    PermissionDeniedError,
    TeachingError,
    TeachingService,
)


@pytest.fixture()
def env(tmp_path):
    conn = connect(tmp_path / "analytics.db")
    migrate(conn)
    teaching = TeachingService(conn)
    cases = ClinicalCaseService(conn)
    attempts = AttemptService(conn)
    analytics = AnalyticsService(conn)

    payload = case_template()
    payload["case_code"] = "RESP-L2-970"
    case, _ = cases.create_case(payload, actor_id="author-1")
    cases.submit_for_review(case.case_id, actor_id="author-1")
    cases.record_review(case.case_id, reviewer_id="r1", decision="approve")
    cases.record_review(case.case_id, reviewer_id="r2", decision="approve")
    cases.publish(case.case_id, actor_id="admin-1")

    course = teaching.create_course("default", "RESP", "呼吸", created_by="admin-1")
    cls = teaching.create_class(course.course_id, "1班", created_by="admin-1")
    teaching.add_member(cls.class_id, "admin-1", "course_admin", actor_id="admin-1")
    teaching.add_member(cls.class_id, "teacher-1", "teacher", actor_id="admin-1")
    teaching.add_member(cls.class_id, "student-1", "student", actor_id="admin-1")
    teaching.add_member(cls.class_id, "student-2", "student", actor_id="admin-1")
    assignment = teaching.create_assignment(
        cls.class_id, case.case_id, "训练", actor_id="teacher-1", publish=True
    )
    yield type("Env", (), {
        "conn": conn, "teaching": teaching, "cases": cases, "attempts": attempts,
        "analytics": analytics, "assignment": assignment, "cls": cls,
    })()
    conn.close()


def _submit_for(env, student_id):
    attempt = env.attempts.create_attempt(env.assignment.assignment_id, student_id=student_id)
    for st in REQUIRED_STEP_TYPES:
        env.attempts.add_step(attempt.attempt_id, actor_id=student_id, step_type=st, content=st + "内容" * 5)
    env.attempts.submit(attempt.attempt_id, actor_id=student_id)
    return attempt


def test_dashboard_requires_class_staff(env):
    with pytest.raises(PermissionDeniedError):
        env.analytics.class_overview(env.cls.class_id, actor_id="student-1")
    with pytest.raises(PermissionDeniedError):
        env.analytics.class_overview(env.cls.class_id, actor_id="outsider")
    overview = env.analytics.class_overview(env.cls.class_id, actor_id="teacher-1")
    assert overview["class_id"] == env.cls.class_id
    assert len(overview["assignments"]) == 1
    assert {s["student_id"] for s in overview["students"]} == {"student-1", "student-2"}


def test_dashboard_counts_attempts(env):
    _submit_for(env, "student-1")
    overview = env.analytics.class_overview(env.cls.class_id, actor_id="teacher-1")
    by_student = {s["student_id"]: s for s in overview["students"]}
    assert by_student["student-1"]["attempts_submitted"] == 1
    assert by_student["student-2"]["attempts_total"] == 0
    assert by_student["student-2"]["attempts_submitted"] == 0
    assert overview["assignments"][0]["students_started"] == 1


def test_risk_flags_rules(env):
    # student-2 has no attempts -> no_attempts flag.
    flags = {f["student_id"]: f for f in env.analytics.risk_flags(env.cls.class_id, actor_id="teacher-1")}
    assert "no_attempts" in flags["student-2"]["reasons"]
    # student-1 submits -> reviewed==0 flag appears; resolve by teacher review.
    attempt = _submit_for(env, "student-1")
    flags = {f["student_id"]: f for f in env.analytics.risk_flags(env.cls.class_id, actor_id="teacher-1")}
    assert "no_reviewed_attempts" in flags["student-1"]["reasons"]
    steps = env.attempts.list_steps(attempt.attempt_id, actor_id="teacher-1")
    env.attempts.record_review(attempt.attempt_id, reviewer_id="teacher-1", notes="ok")
    flags = {f["student_id"]: f for f in env.analytics.risk_flags(env.cls.class_id, actor_id="teacher-1")}
    assert "no_reviewed_attempts" not in flags.get("student-1", {"reasons": []})["reasons"]
    _ = steps


def test_stale_in_progress_flag(env):
    attempt = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-1")
    old = "2026-09-01T00:00:00+00:00"
    env.conn.execute(
        "UPDATE case_attempts SET started_at = ? WHERE attempt_id = ?", (old, attempt.attempt_id)
    )
    env.conn.commit()
    flags = {f["student_id"]: f for f in env.analytics.risk_flags(env.cls.class_id, actor_id="teacher-1")}
    assert any(r.startswith(f"stale_in_progress(>{STALE_IN_PROGRESS_DAYS}d)") for r in flags["student-1"]["reasons"])


def test_intervention_loop(env):
    intervention = env.analytics.record_intervention(
        env.cls.class_id, teacher_id="teacher-1",
        student_id="student-2", reason="未提交任何训练", note="课后提醒",
    )
    assert intervention["status"] == "open"
    with pytest.raises(TeachingError):
        env.analytics.record_intervention(
            env.cls.class_id, teacher_id="teacher-1",
            student_id="teacher-1", reason="not a student",
        )
    with pytest.raises(PermissionDeniedError):
        env.analytics.resolve_intervention(intervention["intervention_id"], actor_id="student-1")
    resolved = env.analytics.resolve_intervention(
        intervention["intervention_id"], actor_id="teacher-1", outcome="已电话沟通"
    )
    assert resolved["status"] == "resolved" and resolved["outcome"] == "已电话沟通"
    with pytest.raises(TeachingError, match="already"):
        env.analytics.resolve_intervention(intervention["intervention_id"], actor_id="teacher-1")
    listing = env.analytics.list_interventions(env.cls.class_id, actor_id="teacher-1")
    assert len(listing) == 1 and listing[0]["status"] == "resolved"


def test_cross_class_staff_cannot_see(env):
    cls2 = env.teaching.create_class(
        env.teaching.list_courses("default")[0].course_id, "2班", created_by="admin-1"
    )
    env.teaching.add_member(cls2.class_id, "admin-1", "course_admin", actor_id="admin-1")
    env.teaching.add_member(cls2.class_id, "teacher-2", "teacher", actor_id="admin-1")
    with pytest.raises(PermissionDeniedError):
        env.analytics.class_overview(env.cls.class_id, actor_id="teacher-2")
    with pytest.raises(PermissionDeniedError):
        env.analytics.risk_flags(env.cls.class_id, actor_id="teacher-2")
    with pytest.raises(PermissionDeniedError):
        env.analytics.list_interventions(env.cls.class_id, actor_id="teacher-2")
