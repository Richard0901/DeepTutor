"""Clinical case API: case library, versions, dual review and publication.

Mounted at ``/api/v1/clinical``.  Publication follows the plan's hard
constraint #3: a case cannot be published without two distinct approvals of
its current version, and published versions are immutable.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from deeptutor.api.routers.teaching import _current_user_id, _to_http, get_conn
from deeptutor.clinical.schemas import CaseValidationError
from deeptutor.clinical.service import ClinicalCaseService
from deeptutor.teaching.service import TeachingError

router = APIRouter()


def get_case_service(
    conn: Any = Depends(get_conn),
) -> ClinicalCaseService:
    return ClinicalCaseService(conn)


class CreateCaseRequest(BaseModel):
    tenant_id: str = Field(default="default", min_length=1, max_length=64)
    payload: dict


class ReviewRequest(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject|request_changes)$")
    comments: str = Field(default="", max_length=4000)


class NewVersionRequest(BaseModel):
    payload: dict


@router.post("/cases")
def create_case(req: CreateCaseRequest, svc: ClinicalCaseService = Depends(get_case_service)):
    try:
        case, version = svc.create_case(
            req.payload, actor_id=_current_user_id(), tenant_id=req.tenant_id
        )
    except CaseValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.errors) from exc
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return {"case": case.__dict__, "version": version.version_id}


@router.get("/cases")
def list_cases(
    tenant_id: str = "default",
    level: str | None = None,
    case_status: str | None = None,
    svc: ClinicalCaseService = Depends(get_case_service),
):
    try:
        cases = svc.list_cases(tenant_id=tenant_id, level=level, status=case_status)
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return [case.__dict__ for case in cases]


@router.get("/cases/{case_id}")
def get_case(case_id: str, svc: ClinicalCaseService = Depends(get_case_service)):
    try:
        case = svc.get_case(case_id)
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return case.__dict__


@router.get("/cases/{case_id}/versions")
def list_versions(case_id: str, svc: ClinicalCaseService = Depends(get_case_service)):
    try:
        svc.get_case(case_id)
        versions = svc.list_versions(case_id)
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return [
        {
            "version_id": v.version_id,
            "case_id": v.case_id,
            "version": v.version,
            "status": v.status,
            "content_hash": v.content_hash,
            "change_note": v.change_note,
            "created_by": v.created_by,
            "created_at": v.created_at,
        }
        for v in versions
    ]


@router.get("/cases/{case_id}/content")
def get_case_content(
    case_id: str,
    version: int | None = None,
    svc: ClinicalCaseService = Depends(get_case_service),
):
    from deeptutor.teaching.service import NotFoundError

    try:
        case = svc.get_case(case_id)
        if version is None:
            content = svc.get_version(case.current_version_id).content  # type: ignore[arg-type]
        else:
            match = [v for v in svc.list_versions(case_id) if v.version == version]
            if not match:
                raise NotFoundError(f"version {version} of case '{case_id}' not found")
            content = match[0].content
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return content


@router.post("/cases/{case_id}/submit-review")
def submit_for_review(case_id: str, svc: ClinicalCaseService = Depends(get_case_service)):
    try:
        case = svc.submit_for_review(case_id, actor_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return case.__dict__


@router.post("/cases/{case_id}/reviews")
def record_review(case_id: str, req: ReviewRequest, svc: ClinicalCaseService = Depends(get_case_service)):
    try:
        case = svc.record_review(
            case_id,
            reviewer_id=_current_user_id(),
            decision=req.decision,
            comments=req.comments,
        )
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return case.__dict__


@router.post("/cases/{case_id}/publish")
def publish_case(case_id: str, svc: ClinicalCaseService = Depends(get_case_service)):
    try:
        case = svc.publish(case_id, actor_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return case.__dict__


@router.post("/cases/{case_id}/versions")
def create_new_version(
    case_id: str, req: NewVersionRequest, svc: ClinicalCaseService = Depends(get_case_service)
):
    try:
        version = svc.create_new_version(req.payload, case_id=case_id, actor_id=_current_user_id())
    except CaseValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.errors) from exc
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return {"version_id": version.version_id, "version": version.version}


@router.post("/cases/{case_id}/publish-new-version")
def publish_new_version(case_id: str, svc: ClinicalCaseService = Depends(get_case_service)):
    try:
        case = svc.publish_new_version(case_id, actor_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return case.__dict__


@router.post("/cases/{case_id}/retire")
def retire_case(case_id: str, svc: ClinicalCaseService = Depends(get_case_service)):
    try:
        case = svc.retire(case_id, actor_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return case.__dict__


@router.get("/cases/{case_id}/reviews")
def list_reviews(case_id: str, svc: ClinicalCaseService = Depends(get_case_service)):
    try:
        case = svc.get_case(case_id)
        reviews = svc.list_reviews(case.current_version_id)  # type: ignore[arg-type]
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return [r.__dict__ for r in reviews]
