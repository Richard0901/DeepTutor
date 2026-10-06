"""TeachingService tests: course/class/membership/assignment rules."""

from __future__ import annotations

import pytest

from deeptutor.clinical.case_import import case_template
from deeptutor.clinical.service import ClinicalCaseService
from deeptutor.teaching.database import connect, migrate
from deeptutor.teaching.service import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    TeachingError,
    TeachingService,
)


@pytest.fixture()
def svc(tmp_path):
    conn = connect(tmp_path / "teaching.db")
    migrate(conn)
    yield TeachingService(conn)
    conn.close()


@pytest.fixture()
def draft_case_id(svc):
    payload = case_template()
    payload["case_code"] = "RESP-L1-900"
    case, _version = ClinicalCaseService(svc._conn).create_case(payload, actor_id="author-1")
    return case.case_id


@pytest.fixture()
def published_case_id(svc):
    payload = case_template()
    payload["case_code"] = "RESP-L1-901"
    service = ClinicalCaseService(svc._conn)
    case, _version = service.create_case(payload, actor_id="author-1")
    service.submit_for_review(case.case_id, actor_id="author-1")
    service.record_review(case.case_id, reviewer_id="reviewer-1", decision="approve")
    service.record_review(case.case_id, reviewer_id="reviewer-2", decision="approve")
    return service.publish(case.case_id, actor_id="admin-1").case_id


def _course(svc, code="RESP"):
    return svc.create_course("default", code, "呼吸系统疾病", created_by="admin-1")


def _class_with_members(svc):
    course = _course(svc)
    cls = svc.create_class(course.course_id, "2026级五年制1班", created_by="admin-1")
    svc.add_member(cls.class_id, "admin-1", "course_admin", actor_id="admin-1")
    svc.add_member(cls.class_id, "teacher-1", "teacher", actor_id="admin-1")
    svc.add_member(cls.class_id, "student-1", "student", actor_id="admin-1")
    return course, cls


def test_create_course_versions_seeded(svc):
    course = _course(svc, "RESP-A")
    rows = svc._conn.execute(
        "SELECT * FROM course_versions WHERE course_id = ?", (course.course_id,)
    ).fetchall()
    assert [r["version"] for r in rows] == [1]


def test_duplicate_course_code_rejected(svc):
    _course(svc, "RESP-DUP")
    with pytest.raises(ConflictError):
        _course(svc, "RESP-DUP")


def test_membership_roles_and_permission_checks(svc):
    _course, cls = _class_with_members(svc)
    membership = svc.require_role(cls.class_id, "teacher-1", allowed=("course_admin", "teacher"))
    assert membership.role == "teacher"
    with pytest.raises(PermissionDeniedError):
        svc.require_role(cls.class_id, "student-1", allowed=("course_admin", "teacher"))
    with pytest.raises(PermissionDeniedError):
        svc.require_role(cls.class_id, "outsider", allowed=("student",))


def test_first_member_of_empty_class_bootstraps(svc):
    _course, cls = _class_with_members(svc)
    fresh = svc.create_class(_course.course_id, "空班", created_by="nobody")
    membership = svc.add_member(fresh.class_id, "first-admin", "course_admin", actor_id="first-admin")
    assert membership.role == "course_admin"


def test_add_member_rejects_unknown_role(svc):
    _course, cls = _class_with_members(svc)
    with pytest.raises(TeachingError):
        svc.add_member(cls.class_id, "u9", "principal", actor_id="admin-1")


def test_duplicate_active_membership_rejected_but_rejoin_allowed(svc):
    _course, cls = _class_with_members(svc)
    with pytest.raises(ConflictError):
        svc.add_member(cls.class_id, "student-1", "student", actor_id="admin-1")
    svc.remove_member(cls.class_id, "student-1", actor_id="admin-1")
    membership = svc.add_member(cls.class_id, "student-1", "student", actor_id="admin-1")
    assert membership.dropped_at is None


def test_student_cannot_manage_members(svc):
    _course, cls = _class_with_members(svc)
    with pytest.raises(PermissionDeniedError):
        svc.add_member(cls.class_id, "intruder", "student", actor_id="student-1")


def test_membership_listing_blocked_for_outsiders(svc):
    _course, cls = _class_with_members(svc)
    with pytest.raises(PermissionDeniedError):
        svc.list_members(cls.class_id, actor_id="outsider")
    assert len(svc.list_members(cls.class_id, actor_id="student-1")) == 3


def test_assignment_requires_published_case(svc, published_case_id):
    course, cls = _class_with_members(svc)
    assignment = svc.create_assignment(
        cls.class_id, published_case_id, "L1 肺炎训练", actor_id="teacher-1", publish=True
    )
    assert assignment.status == "open"
    with pytest.raises(PermissionDeniedError):
        svc.create_assignment(cls.class_id, published_case_id, "x", actor_id="student-1")


def test_assignment_rejects_unpublished_case(svc, draft_case_id):
    _course, cls = _class_with_members(svc)
    with pytest.raises(TeachingError):
        svc.create_assignment(cls.class_id, draft_case_id, "未发布病例", actor_id="teacher-1")


def test_classes_for_user_scoping(svc):
    _course, cls = _class_with_members(svc)
    other = svc.create_class(_course.course_id, "2班", created_by="admin-1")
    svc.add_member(other.class_id, "student-2", "student", actor_id="admin-1")
    classes = {c.class_id for c in svc.classes_for_user("student-1")}
    assert cls.class_id in classes and other.class_id not in classes


def test_get_course_rejects_cross_tenant(svc):
    course = svc.create_course("tenant-a", "RESP-T", "标题", created_by="admin-1")
    with pytest.raises(NotFoundError):
        svc.get_course(course.course_id, tenant_id="tenant-b")
