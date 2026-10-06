"""HTTP permission tests for the teaching-domain router (/api/v1/teaching).

Follows the repo convention of standalone FastAPI apps (see
tests/api/test_book_permission_api.py): mount only the router under test,
inject the acting user via a request-scoped contextvar dependency, and
isolate the teaching database with ``DEEPTUTOR_TEACHING_DB``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import teaching
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.teaching.database import connect, migrate


@pytest.fixture()
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "teaching.db"
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
    app.include_router(teaching.router, prefix="/api/v1/teaching", dependencies=[Depends(install_user)])
    return TestClient(app)


def test_course_crud_and_duplicate_code(db_path):
    admin = _client(db_path, "admin-1")
    resp = admin.post(
        "/api/v1/teaching/courses",
        json={"tenant_id": "default", "code": "RESP", "title": "呼吸系统疾病"},
    )
    assert resp.status_code == 200
    assert resp.json()["code"] == "RESP"
    dup = admin.post(
        "/api/v1/teaching/courses",
        json={"tenant_id": "default", "code": "RESP", "title": "重复"},
    )
    assert dup.status_code == 409
    listing = admin.get("/api/v1/teaching/courses", params={"tenant_id": "default"})
    assert listing.status_code == 200 and len(listing.json()) == 1


def test_membership_management_permissions(db_path):
    admin = _client(db_path, "admin-1")
    course_id = admin.post(
        "/api/v1/teaching/courses", json={"code": "RESP", "title": "呼吸"}
    ).json()["course_id"]
    class_id = admin.post(
        f"/api/v1/teaching/courses/{course_id}/classes", json={"name": "1班"}
    ).json()["class_id"]

    teacher = _client(db_path, "teacher-1")
    added = teacher.post(
        f"/api/v1/teaching/classes/{class_id}/members",
        json={"user_id": "teacher-1", "role": "teacher"},
    )
    # Bootstrap: the empty class accepts its first member.
    assert added.status_code == 200
    student = _client(db_path, "student-1")
    denied = student.post(
        f"/api/v1/teaching/classes/{class_id}/members",
        json={"user_id": "student-1", "role": "student"},
    )
    assert denied.status_code == 403
    teacher_add = teacher.post(
        f"/api/v1/teaching/classes/{class_id}/members",
        json={"user_id": "student-1", "role": "student"},
    )
    assert teacher_add.status_code == 200
    roster_denied = _client(db_path, "outsider").get(
        f"/api/v1/teaching/classes/{class_id}/members"
    )
    assert roster_denied.status_code == 403
    roster = student.get(f"/api/v1/teaching/classes/{class_id}/members")
    assert roster.status_code == 200 and len(roster.json()) == 2


def test_unknown_role_rejected(db_path):
    admin = _client(db_path, "admin-1")
    course_id = admin.post(
        "/api/v1/teaching/courses", json={"code": "RESP", "title": "呼吸"}
    ).json()["course_id"]
    class_id = admin.post(
        f"/api/v1/teaching/courses/{course_id}/classes", json={"name": "1班"}
    ).json()["class_id"]
    resp = admin.post(
        f"/api/v1/teaching/classes/{class_id}/members",
        json={"user_id": "u1", "role": "principal"},
    )
    assert resp.status_code == 422


def test_assignment_requires_published_case_over_http(db_path):
    admin = _client(db_path, "admin-1")
    course_id = admin.post(
        "/api/v1/teaching/courses", json={"code": "RESP", "title": "呼吸"}
    ).json()["course_id"]
    class_id = admin.post(
        f"/api/v1/teaching/courses/{course_id}/classes", json={"name": "1班"}
    ).json()["class_id"]
    admin.post(
        f"/api/v1/teaching/classes/{class_id}/members",
        json={"user_id": "admin-1", "role": "course_admin"},
    )
    # An assignment pointing at a case that does not exist at all.
    resp = admin.post(
        f"/api/v1/teaching/classes/{class_id}/assignments",
        json={"case_id": "missing-case", "title": "训练"},
    )
    assert resp.status_code == 404
