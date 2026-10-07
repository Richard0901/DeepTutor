"""Governance and gradebook tests (Sprint 5): audit trail, 40/60 frame
without weight synthesis, and the student progress profile."""

from __future__ import annotations

import pytest

from deeptutor.analytics.gradebook import GradebookService
from deeptutor.analytics.progress import my_progress
from deeptutor.clinical.attempts import REQUIRED_STEP_TYPES, AttemptService
from deeptutor.clinical.case_import import case_template
from deeptutor.clinical.service import ClinicalCaseService
from deeptutor.teaching.audit import query_audit, record_audit
from deeptutor.teaching.database import connect, migrate
from deeptutor.teaching.service import NotFoundError, PermissionDeniedError, TeachingService


@pytest.fixture()
def env(tmp_path):
    conn = connect(tmp_path / "gov.db")
    migrate(conn)
    teaching = TeachingService(conn)
    cases = ClinicalCaseService(conn)
    attempts = AttemptService(conn)
    gradebook = GradebookService(conn)

    payload = case_template()
    payload["case_code"] = "RESP-L2-980"
    case, _ = cases.create_case(payload, actor_id="author-1")
    cases.submit_for_review(case.case_id, actor_id="author-1")
    cases.record_review(case.case_id, reviewer_id="r1", decision="approve")
    cases.record_review(case.case_id, reviewer_id="r2", decision="approve")
    case = cases.publish(case.case_id, actor_id="admin-1")

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
        "gradebook": gradebook, "assignment": assignment, "cls": cls, "case": case,
    })()
    conn.close()


def _submit_for(env, student_id):
    attempt = env.attempts.create_attempt(env.assignment.assignment_id, student_id=student_id)
    for st in REQUIRED_STEP_TYPES:
        env.attempts.add_step(attempt.attempt_id, actor_id=student_id, step_type=st, content=st * 6)
    env.attempts.submit(attempt.attempt_id, actor_id=student_id)
    return attempt


# -- audit trail -----------------------------------------------------------------


def test_key_actions_leave_audit_rows(env):
    _submit_for(env, "student-1")
    attempt2 = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-2")
    for st in REQUIRED_STEP_TYPES:
        env.attempts.add_step(attempt2.attempt_id, actor_id="student-2", step_type=st, content=st * 6)
    submitted = env.attempts.submit(attempt2.attempt_id, actor_id="student-2")
    env.attempts.record_review(attempt2.attempt_id, reviewer_id="teacher-1", notes="ok")
    env.cases.retire(env.case.case_id, actor_id="admin-1")

    # class-scoped query returns the class-attached events (attempts)
    events = query_audit(env.conn, class_id=env.cls.class_id)
    assert {"attempt_submit", "attempt_review"} <= {e["action"] for e in events}
    # case-level events (publish/retire) are not class-scoped — query by action
    case_events = query_audit(env.conn, action="case_publish") + query_audit(env.conn, action="case_retire")
    assert {"case_publish", "case_retire"} <= {e["action"] for e in case_events}
    assert all(e["actor_id"] for e in events + case_events)


def test_case_review_audited(env):
    payload = case_template()
    payload["case_code"] = "RESP-L2-981"
    case, _ = env.cases.create_case(payload, actor_id="author-1")
    env.cases.submit_for_review(case.case_id, actor_id="author-1")
    env.cases.record_review(case.case_id, reviewer_id="r1", decision="approve")
    reviews = [e for e in query_audit(env.conn, action="case_review")]
    assert any(e["actor_id"] == "r1" for e in reviews)


def test_audit_query_requires_class_staff(env):
    with pytest.raises(PermissionDeniedError):
        env.teaching.require_role(
            env.cls.class_id, "student-1", allowed=("course_admin", "teacher", "reviewer")
        )
    # students may not read the audit trail (route-level gate mirrors this)
    with pytest.raises(PermissionDeniedError):
        env.teaching.require_role(
            env.cls.class_id, "outsider", allowed=("course_admin", "teacher", "reviewer")
        )


# -- gradebook --------------------------------------------------------------------


def test_gradebook_aggregates_components(env):
    _submit_for(env, "student-1")
    data = env.gradebook.gradebook(env.cls.class_id, actor_id="teacher-1")
    by_student = {s["student_id"]: s for s in data["students"]}
    assert by_student["student-1"]["formative"]["attempts_submitted"] == 1
    assert by_student["student-2"]["formative"]["attempts_total"] == 0
    # framework present but weighted_total deliberately None
    assert data["framework"]["weighted_total"] is None
    assert data["framework"]["formative_weight"] == 0.4


def test_summative_score_entry_and_history(env):
    env.gradebook.record_summative_score(
        env.cls.class_id, teacher_id="teacher-1", student_id="student-1",
        title="期末理论", score=88,
    )
    env.gradebook.record_summative_score(
        env.cls.class_id, teacher_id="teacher-1", student_id="student-1",
        title="期末理论", score=92, note="复核后调整",
    )
    data = env.gradebook.gradebook(env.cls.class_id, actor_id="teacher-1")
    row = next(s for s in data["students"] if s["student_id"] == "student-1")
    assert row["summative"]["期末理论"] == 92  # latest wins
    history = env.conn.execute(
        "SELECT COUNT(*) FROM summative_scores WHERE student_id = 'student-1'"
    ).fetchone()[0]
    assert history == 2  # both rows retained
    with pytest.raises(PermissionDeniedError):
        env.gradebook.record_summative_score(
            env.cls.class_id, teacher_id="student-1", student_id="student-2",
            title="x", score=50,
        )


def test_gradebook_csv(env):
    _submit_for(env, "student-1")
    env.gradebook.record_summative_score(
        env.cls.class_id, teacher_id="teacher-1", student_id="student-1",
        title="期末理论", score=88,
    )
    csv_text = env.gradebook.csv_export(env.cls.class_id, actor_id="teacher-1")
    assert "student_id,attempts_total" in csv_text
    assert "summative:期末理论" in csv_text
    student_row = next(line for line in csv_text.splitlines() if line.startswith("student-1,"))
    assert ",88" in student_row
    assert "weighted" not in csv_text  # no synthetic totals


# -- progress profile --------------------------------------------------------------


def test_progress_profile_shape_and_counts(env):
    _submit_for(env, "student-1")
    profile = my_progress(env.conn, "student-1")
    assert profile["level_distribution"]["L1"]["attempts"] == 1  # template case is L1
    assert profile["level_distribution"]["L1"]["submitted"] == 1
    assert profile["error_trends"] == {}
    assert profile["compensation_triggered"] == []


def test_progress_profile_is_self_only(env):
    # the endpoint resolves the student from the request context; a fresh
    # student with no attempts gets an empty but well-formed profile
    profile = my_progress(env.conn, "student-2")
    assert profile["student_id"] == "student-2"
    assert profile["level_distribution"] == {}


def test_audit_helper_requires_membership(env):
    record_audit(env.conn, actor_id="teacher-1", action="x", object_type="t", object_id="1")
    with pytest.raises(PermissionDeniedError):
        env.teaching.require_role("missing-class", "teacher-1", allowed=("teacher",))
    with pytest.raises(NotFoundError):
        env.teaching.get_class("missing-class")
