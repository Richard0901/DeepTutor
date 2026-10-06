"""HTTP tests for the clinical case router (/api/v1/clinical): dual review,
publication gates and the student attempt journey, over HTTP."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import clinical_cases
from deeptutor.clinical.case_import import case_template
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.teaching.database import connect, migrate

REQUIRED_STEPS = (
    "problem_presentation",
    "differential_diagnosis",
    "key_evidence",
    "investigation",
    "disposition",
)


@pytest.fixture()
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "clinical.db"
    monkeypatch.setenv("DEEPTUTOR_TEACHING_DB", str(path))
    conn = connect(path)
    migrate(conn)
    conn.close()
    return path


def _client(db_path: Path, user_id: str) -> TestClient:
    user = CurrentUser(
        id=user_id,
        username=user_id,
        role="user",
        scope=UserScope(kind="user", user_id=user_id, root=db_path.parent),
    )

    async def install_user() -> Iterator[CurrentUser]:
        token = set_current_user(user)
        try:
            yield user
        finally:
            reset_current_user(token)

    app = FastAPI()
    app.include_router(
        clinical_cases.router, prefix="/api/v1/clinical", dependencies=[Depends(install_user)]
    )
    return TestClient(app)


def _publish_case(db_path: Path, case_code: str) -> str:
    author = _client(db_path, "author-1")
    payload = case_template()
    payload["case_code"] = case_code
    resp = author.post("/api/v1/clinical/cases", json={"payload": payload})
    assert resp.status_code == 200, resp.text
    case_id = resp.json()["case"]["case_id"]
    assert author.post(f"/api/v1/clinical/cases/{case_id}/submit-review").status_code == 200
    for reviewer in ("reviewer-1", "reviewer-2"):
        r = _client(db_path, reviewer).post(
            f"/api/v1/clinical/cases/{case_id}/reviews", json={"decision": "approve"}
        )
        assert r.status_code == 200, r.text
    publish = _client(db_path, "admin-1").post(f"/api/v1/clinical/cases/{case_id}/publish")
    assert publish.status_code == 200, publish.text
    return case_id


def test_case_validation_error_returns_400(db_path):
    client = _client(db_path, "author-1")
    payload = case_template()
    payload["case_code"] = "RESP-L1-001"
    payload["level"] = "L7"
    resp = client.post("/api/v1/clinical/cases", json={"payload": payload})
    assert resp.status_code == 400
    assert any("level" in detail for detail in resp.json()["detail"])


def test_dual_review_and_publication_over_http(db_path):
    author = _client(db_path, "author-1")
    payload = case_template()
    payload["case_code"] = "RESP-L2-900"
    case_id = author.post("/api/v1/clinical/cases", json={"payload": payload}).json()["case"]["case_id"]

    # Publishing without reviews is refused.
    early = _client(db_path, "admin-1").post(f"/api/v1/clinical/cases/{case_id}/publish")
    assert early.status_code == 400

    assert author.post(f"/api/v1/clinical/cases/{case_id}/submit-review").status_code == 200
    reviewer1 = _client(db_path, "reviewer-1")
    # The author cannot review their own case.
    self_review = author.post(
        f"/api/v1/clinical/cases/{case_id}/reviews", json={"decision": "approve"}
    )
    assert self_review.status_code == 400
    assert reviewer1.post(
        f"/api/v1/clinical/cases/{case_id}/reviews", json={"decision": "approve"}
    ).status_code == 200
    # One approval is not enough yet.
    assert _client(db_path, "admin-1").post(f"/api/v1/clinical/cases/{case_id}/publish").status_code == 400
    reviewer2 = _client(db_path, "reviewer-2")
    assert reviewer2.post(
        f"/api/v1/clinical/cases/{case_id}/reviews", json={"decision": "approve"}
    ).status_code == 200
    published = _client(db_path, "admin-1").post(f"/api/v1/clinical/cases/{case_id}/publish")
    assert published.status_code == 200 and published.json()["status"] == "published"
    # After publication the case leaves the review workflow entirely.
    assert reviewer1.post(
        f"/api/v1/clinical/cases/{case_id}/reviews", json={"decision": "approve"}
    ).status_code == 400


def test_student_attempt_journey_over_http(db_path):
    from deeptutor.teaching.database import connect as _connect
    from deeptutor.teaching.service import TeachingService

    case_id = _publish_case(db_path, "RESP-L1-910")

    # Seed the class and assignment directly through the service layer (the
    # teaching router is covered by its own test file).
    conn = _connect(db_path)
    teaching = TeachingService(conn)
    course = teaching.create_course("default", "RESP", "呼吸系统疾病", created_by="teacher-1")
    cls = teaching.create_class(course.course_id, "1班", created_by="teacher-1")
    teaching.add_member(cls.class_id, "admin-1", "course_admin", actor_id="admin-1")
    teaching.add_member(cls.class_id, "teacher-1", "teacher", actor_id="admin-1")
    teaching.add_member(cls.class_id, "student-1", "student", actor_id="admin-1")
    teaching.add_member(cls.class_id, "student-2", "student", actor_id="admin-1")
    assignment = teaching.create_assignment(
        cls.class_id, case_id, "L1 训练", actor_id="teacher-1", publish=True
    )
    conn.close()

    student = _client(db_path, "student-1")
    outsider = _client(db_path, "student-x")
    teacher = _client(db_path, "teacher-1")

    created = student.post(
        "/api/v1/clinical/attempts", json={"assignment_id": assignment.assignment_id}
    )
    assert created.status_code == 200, created.text
    attempt_id = created.json()["attempt_id"]

    # Non-students cannot open attempts on the assignment.
    assert outsider.post(
        "/api/v1/clinical/attempts", json={"assignment_id": assignment.assignment_id}
    ).status_code == 403

    # Submitting early fails with a 400 listing missing step types.
    early = student.post(f"/api/v1/clinical/attempts/{attempt_id}/submit")
    assert early.status_code == 400 and "problem_presentation" in early.json()["detail"]

    # Only the owner can record steps; unknown types are rejected (422).
    denied_step = outsider.post(
        f"/api/v1/clinical/attempts/{attempt_id}/steps",
        json={"step_type": "disposition", "content": "x"},
    )
    assert denied_step.status_code == 403
    bad_type = student.post(
        f"/api/v1/clinical/attempts/{attempt_id}/steps",
        json={"step_type": "free_form", "content": "x"},
    )
    assert bad_type.status_code == 422

    for step_type in REQUIRED_STEPS:
        resp = student.post(
            f"/api/v1/clinical/attempts/{attempt_id}/steps",
            json={"step_type": step_type, "content": f"{step_type}：……"},
        )
        assert resp.status_code == 200, resp.text
    assert student.post(f"/api/v1/clinical/attempts/{attempt_id}/submit").status_code == 200

    # Reads: owner and class teacher see it; outsiders get 404 (no leak).
    assert student.get(f"/api/v1/clinical/attempts/{attempt_id}").status_code == 200
    assert teacher.get(f"/api/v1/clinical/attempts/{attempt_id}").status_code == 200
    assert outsider.get(f"/api/v1/clinical/attempts/{attempt_id}").status_code == 404

    # Review: class staff only, with per-step marks.
    steps = teacher.get(f"/api/v1/clinical/attempts/{attempt_id}/steps").json()
    cross_class = _client(db_path, "teacher-2")
    assert (
        cross_class.post(
            f"/api/v1/clinical/attempts/{attempt_id}/review", json={"notes": "x"}
        ).status_code
        == 403
    )
    reviewed = teacher.post(
        f"/api/v1/clinical/attempts/{attempt_id}/review",
        json={
            "notes": "鉴别诊断需补齐",
            "step_marks": [
                {"step_id": steps[0]["step_id"], "is_correct": False, "comment": "漏诱因"}
            ],
        },
    )
    assert reviewed.status_code == 200 and reviewed.json()["status"] == "reviewed"
    marked = [
        s
        for s in teacher.get(f"/api/v1/clinical/attempts/{attempt_id}/steps").json()
        if s["step_id"] == steps[0]["step_id"]
    ][0]
    assert marked["is_correct"] == 0 and marked["reviewed_by_teacher"] == 1
