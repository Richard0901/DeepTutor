"""Teaching-domain API: courses, classes, memberships, assignments.

Mounted at ``/api/v1/teaching``.  These endpoints sit on the central
teaching database (see :mod:`deeptutor.teaching.database`) and are separate
from the upstream study-course endpoints at ``/api/courses``.
"""

from __future__ import annotations

import sqlite3
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from deeptutor.multi_user.context import get_current_user
from deeptutor.teaching.database import connect, migrate
from deeptutor.teaching.service import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    TeachingError,
    TeachingService,
)

router = APIRouter()


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        migrate(conn)
        yield conn
    finally:
        conn.close()


def get_service(conn: sqlite3.Connection = Depends(get_conn)) -> TeachingService:
    return TeachingService(conn)


def _current_user_id() -> str:
    return get_current_user().id


def _to_http(exc: TeachingError) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, PermissionDeniedError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


class CreateCourseRequest(BaseModel):
    tenant_id: str = Field(default="default", min_length=1, max_length=64)
    code: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class CreateClassRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    semester: str = Field(default="", max_length=32)


class AddMemberRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64)
    role: str = Field(..., pattern="^(course_admin|teacher|reviewer|student)$")


class CreateAssignmentRequest(BaseModel):
    case_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    due_at: str | None = None
    publish: bool = False


class AssignmentStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(draft|open|closed)$")


@router.get("/my/classes")
def my_classes(tenant_id: str = "default", svc: TeachingService = Depends(get_service)):
    """Classes the current user is an active member of (student workbench
    entry point)."""
    try:
        classes = svc.classes_for_user(_current_user_id(), tenant_id=tenant_id)
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return [cls.__dict__ for cls in classes]


@router.post("/courses")
def create_course(req: CreateCourseRequest, svc: TeachingService = Depends(get_service)):
    try:
        course = svc.create_course(
            req.tenant_id,
            req.code,
            req.title,
            created_by=_current_user_id(),
            description=req.description,
        )
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return course.__dict__


@router.get("/courses")
def list_courses(tenant_id: str = "default", svc: TeachingService = Depends(get_service)):
    return [course.__dict__ for course in svc.list_courses(tenant_id)]


@router.post("/courses/{course_id}/classes")
def create_class(course_id: str, req: CreateClassRequest, svc: TeachingService = Depends(get_service)):
    try:
        cls = svc.create_class(
            course_id, req.name, created_by=_current_user_id(), semester=req.semester
        )
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return cls.__dict__


@router.get("/courses/{course_id}/classes")
def list_classes(course_id: str, svc: TeachingService = Depends(get_service)):
    try:
        return [cls.__dict__ for cls in svc.list_classes(course_id)]
    except TeachingError as exc:
        raise _to_http(exc) from exc


@router.post("/classes/{class_id}/members")
def add_member(class_id: str, req: AddMemberRequest, svc: TeachingService = Depends(get_service)):
    try:
        membership = svc.add_member(
            class_id, req.user_id, req.role, actor_id=_current_user_id()
        )
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return membership.__dict__


@router.get("/classes/{class_id}/members")
def list_members(class_id: str, svc: TeachingService = Depends(get_service)):
    try:
        members = svc.list_members(class_id, actor_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return [m.__dict__ for m in members]


@router.delete("/classes/{class_id}/members/{user_id}")
def remove_member(class_id: str, user_id: str, svc: TeachingService = Depends(get_service)):
    try:
        svc.remove_member(class_id, user_id, actor_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return {"removed": user_id}


@router.post("/classes/{class_id}/assignments")
def create_assignment(
    class_id: str, req: CreateAssignmentRequest, svc: TeachingService = Depends(get_service)
):
    try:
        assignment = svc.create_assignment(
            class_id,
            req.case_id,
            req.title,
            actor_id=_current_user_id(),
            description=req.description,
            due_at=req.due_at,
            publish=req.publish,
        )
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return assignment.__dict__


@router.get("/classes/{class_id}/assignments")
def list_assignments(class_id: str, svc: TeachingService = Depends(get_service)):
    try:
        assignments = svc.list_assignments(class_id, actor_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return [a.__dict__ for a in assignments]


@router.post("/assignments/{assignment_id}/status")
def set_assignment_status(
    assignment_id: str, req: AssignmentStatusRequest, svc: TeachingService = Depends(get_service)
):
    try:
        assignment = svc.set_assignment_status(
            assignment_id, req.status, actor_id=_current_user_id()
        )
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return assignment.__dict__


@router.get("/audit")
def query_audit_endpoint(
    class_id: str,
    action: str | None = None,
    limit: int = 100,
    svc: TeachingService = Depends(get_service),
):
    """Class-scoped audit trail (Sprint 5): class staff only."""
    try:
        svc.require_role(class_id, _current_user_id(), allowed=("course_admin", "teacher", "reviewer"))
    except TeachingError as exc:
        raise _to_http(exc) from exc
    from deeptutor.teaching.audit import query_audit

    return query_audit(
        svc._conn, class_id=class_id, action=action, limit=limit
    )
