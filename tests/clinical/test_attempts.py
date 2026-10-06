"""AttemptService tests: lifecycle, step gates, ownership and staff review."""

from __future__ import annotations

import pytest

from deeptutor.clinical.attempts import (
    REQUIRED_STEP_TYPES,
    AttemptService,
    AttemptStateError,
)
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
    conn = connect(tmp_path / "attempts.db")
    migrate(conn)
    teaching = TeachingService(conn)
    cases = ClinicalCaseService(conn)
    attempts = AttemptService(conn)

    course = teaching.create_course("default", "RESP", "呼吸系统疾病", created_by="admin-1")
    cls = teaching.create_class(course.course_id, "2026级1班", created_by="admin-1")
    teaching.add_member(cls.class_id, "admin-1", "course_admin", actor_id="admin-1")
    teaching.add_member(cls.class_id, "teacher-1", "teacher", actor_id="admin-1")
    teaching.add_member(cls.class_id, "student-1", "student", actor_id="admin-1")
    teaching.add_member(cls.class_id, "student-2", "student", actor_id="admin-1")
    # A second class with its own teacher, for cross-class denial tests.
    cls2 = teaching.create_class(course.course_id, "2026级2班", created_by="admin-1")
    teaching.add_member(cls2.class_id, "admin-1", "course_admin", actor_id="admin-1")
    teaching.add_member(cls2.class_id, "teacher-2", "teacher", actor_id="admin-1")
    teaching.add_member(cls2.class_id, "student-x", "student", actor_id="admin-1")

    payload = case_template()
    payload["case_code"] = "RESP-L1-800"
    case, _v = cases.create_case(payload, actor_id="author-1")
    cases.submit_for_review(case.case_id, actor_id="author-1")
    cases.record_review(case.case_id, reviewer_id="r1", decision="approve")
    cases.record_review(case.case_id, reviewer_id="r2", decision="approve")
    case = cases.publish(case.case_id, actor_id="admin-1")
    assignment = teaching.create_assignment(
        cls.class_id, case.case_id, "L1 肺炎训练", actor_id="teacher-1", publish=True
    )
    yield type(
        "Env", (), {
            "conn": conn, "teaching": teaching, "cases": cases,
            "attempts": attempts, "assignment": assignment, "class": cls,
        }
    )()
    conn.close()


def _full_steps(svc, attempt_id):
    for step_type in REQUIRED_STEP_TYPES:
        svc.add_step(attempt_id, actor_id="student-1", step_type=step_type, content=f"{step_type} 内容")


def test_create_attempt_requires_open_assignment(env):
    attempt = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-1")
    assert attempt.status == "in_progress"
    env.teaching.set_assignment_status(env.assignment.assignment_id, "closed", actor_id="teacher-1")
    with pytest.raises(AttemptStateError):
        env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-2")


def test_create_attempt_requires_student_membership(env):
    with pytest.raises(PermissionDeniedError):
        env.attempts.create_attempt(env.assignment.assignment_id, student_id="teacher-1")
    with pytest.raises(PermissionDeniedError):
        env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-x")


def test_retired_case_blocks_new_attempts(env):
    env.cases.retire(env.assignment.case_id, actor_id="admin-1")
    with pytest.raises(AttemptStateError):
        env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-1")


def test_steps_are_append_only_and_locked_after_submit(env):
    attempt = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-1")
    _full_steps(env.attempts, attempt.attempt_id)
    submitted = env.attempts.submit(attempt.attempt_id, actor_id="student-1")
    assert submitted.status == "submitted" and submitted.submitted_at
    with pytest.raises(AttemptStateError):
        env.attempts.add_step(
            attempt.attempt_id, actor_id="student-1", step_type="reassessment", content="再评估"
        )
    # Steps recorded before submit are immutable — no update/delete API exists;
    # verify the raw rows were never touched by submit.
    rows = env.conn.execute(
        "SELECT updated_at, created_at FROM reasoning_steps WHERE attempt_id = ?",
        (attempt.attempt_id,),
    ).fetchall()
    assert all(row["updated_at"] == row["created_at"] for row in rows)


def test_submit_requires_all_five_step_types(env):
    attempt = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-1")
    with pytest.raises(AttemptStateError) as excinfo:
        env.attempts.submit(attempt.attempt_id, actor_id="student-1")
    assert "problem_presentation" in str(excinfo.value)
    env.attempts.add_step(
        attempt.attempt_id, actor_id="student-1",
        step_type="problem_presentation", content="患者为青年男性……",
    )
    with pytest.raises(AttemptStateError):
        env.attempts.submit(attempt.attempt_id, actor_id="student-1")
    _full_steps(env.attempts, attempt.attempt_id)
    assert env.attempts.submit(attempt.attempt_id, actor_id="student-1").status == "submitted"


def test_step_type_validation(env):
    attempt = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-1")
    with pytest.raises(TeachingError):
        env.attempts.add_step(
            attempt.attempt_id, actor_id="student-1", step_type="free_form", content="x"
        )
    with pytest.raises(TeachingError):
        env.attempts.add_step(
            attempt.attempt_id, actor_id="student-1", step_type="disposition", content="  "
        )


def test_only_owner_can_step_or_submit(env):
    attempt = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-1")
    with pytest.raises(PermissionDeniedError):
        env.attempts.add_step(
            attempt.attempt_id, actor_id="student-2", step_type="disposition", content="x"
        )
    with pytest.raises(PermissionDeniedError):
        env.attempts.submit(attempt.attempt_id, actor_id="teacher-1")


def test_owner_visibility_only(env):
    attempt = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-1")
    assert env.attempts.get_attempt(attempt.attempt_id, actor_id="student-1").attempt_id
    assert env.attempts.get_attempt(attempt.attempt_id, actor_id="teacher-1").attempt_id
    with pytest.raises(NotFoundError):
        env.attempts.get_attempt(attempt.attempt_id, actor_id="student-x")
    with pytest.raises(NotFoundError):
        env.attempts.get_attempt(attempt.attempt_id, actor_id="teacher-2")  # cross-class staff


def test_listing_scopes_by_role(env):
    a1 = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-1")
    a2 = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-2")
    own = env.attempts.list_attempts_for_assignment(env.assignment.assignment_id, actor_id="student-1")
    assert [a.attempt_id for a in own] == [a1.attempt_id]
    all_attempts = env.attempts.list_attempts_for_assignment(
        env.assignment.assignment_id, actor_id="teacher-1"
    )
    assert {a.attempt_id for a in all_attempts} == {a1.attempt_id, a2.attempt_id}
    # Cross-class teacher sees an empty list, not an error (no leak).
    assert env.attempts.list_attempts_for_assignment(env.assignment.assignment_id, actor_id="teacher-2") == []


def test_teacher_review_marks_steps(env):
    attempt = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-1")
    _full_steps(env.attempts, attempt.attempt_id)
    env.attempts.submit(attempt.attempt_id, actor_id="student-1")
    steps = env.attempts.list_steps(attempt.attempt_id, actor_id="teacher-1")
    marks = [
        {"step_id": steps[0].step_id, "is_correct": False, "comment": "问题表征遗漏诱因"}
    ]
    reviewed = env.attempts.record_review(
        attempt.attempt_id, reviewer_id="teacher-1", notes="需补鉴别诊断", step_marks=marks
    )
    assert reviewed.status == "reviewed" and reviewed.reviewer_id == "teacher-1"
    marked = [s for s in env.attempts.list_steps(attempt.attempt_id, actor_id="teacher-1")
              if s.step_id == marks[0]["step_id"]][0]
    assert marked.is_correct == 0 and marked.reviewed_by_teacher == 1
    assert marked.teacher_override == "问题表征遗漏诱因"


def test_review_requires_class_staff_and_submitted_status(env):
    attempt = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-1")
    _full_steps(env.attempts, attempt.attempt_id)
    env.attempts.submit(attempt.attempt_id, actor_id="student-1")
    with pytest.raises(PermissionDeniedError):
        env.attempts.record_review(attempt.attempt_id, reviewer_id="teacher-2", notes="x")
    with pytest.raises(PermissionDeniedError):
        env.attempts.record_review(attempt.attempt_id, reviewer_id="student-2", notes="x")
    with pytest.raises(NotFoundError):
        env.attempts.record_review(attempt.attempt_id, reviewer_id="teacher-1",
                                   step_marks=[{"step_id": "nope", "is_correct": True}])


def test_multiple_attempts_are_kept(env):
    first = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-1")
    _full_steps(env.attempts, first.attempt_id)
    env.attempts.submit(first.attempt_id, actor_id="student-1")
    second = env.attempts.create_attempt(env.assignment.assignment_id, student_id="student-1")
    assert first.attempt_id != second.attempt_id
    own = env.attempts.list_attempts_for_assignment(env.assignment.assignment_id, actor_id="student-1")
    assert len(own) == 2


def test_unknown_assignment(env):
    with pytest.raises(NotFoundError):
        env.attempts.create_attempt("missing-assignment", student_id="student-1")
