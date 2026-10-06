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
from deeptutor.clinical.attempts import STEP_TYPES, AttemptService
from deeptutor.clinical.schemas import CaseValidationError
from deeptutor.clinical.service import ClinicalCaseService
from deeptutor.teaching.service import TeachingError

router = APIRouter()


def get_case_service(
    conn: Any = Depends(get_conn),
) -> ClinicalCaseService:
    return ClinicalCaseService(conn)


def get_attempt_service(conn: Any = Depends(get_conn)) -> AttemptService:
    return AttemptService(conn)


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


# ---------------------------------------------------------------------------
# Student attempts and structured reasoning (plan WP4)
# ---------------------------------------------------------------------------


class CreateAttemptRequest(BaseModel):
    assignment_id: str = Field(..., min_length=1)


class AddStepRequest(BaseModel):
    step_type: str = Field(..., pattern="^(problem_presentation|differential_diagnosis|key_evidence|investigation|disposition|reassessment)$")
    content: str = Field(..., min_length=1, max_length=20000)


class ReviewAttemptRequest(BaseModel):
    notes: str = Field(default="", max_length=8000)
    step_marks: list[dict] = Field(default_factory=list)


@router.post("/attempts")
def create_attempt(
    req: CreateAttemptRequest, svc: AttemptService = Depends(get_attempt_service)
):
    try:
        attempt = svc.create_attempt(req.assignment_id, student_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return attempt.__dict__


@router.get("/attempts")
def list_attempts(
    assignment_id: str, svc: AttemptService = Depends(get_attempt_service)
):
    try:
        attempts = svc.list_attempts_for_assignment(
            assignment_id, actor_id=_current_user_id()
        )
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return [a.__dict__ for a in attempts]


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: str, svc: AttemptService = Depends(get_attempt_service)):
    try:
        attempt = svc.get_attempt(attempt_id, actor_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return attempt.__dict__


@router.get("/attempts/{attempt_id}/steps")
def list_steps(attempt_id: str, svc: AttemptService = Depends(get_attempt_service)):
    try:
        steps = svc.list_steps(attempt_id, actor_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return [s.__dict__ for s in steps]


@router.post("/attempts/{attempt_id}/steps")
def add_step(
    attempt_id: str, req: AddStepRequest, svc: AttemptService = Depends(get_attempt_service)
):
    try:
        if req.step_type not in STEP_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unknown step type '{req.step_type}'",
            )
        step = svc.add_step(
            attempt_id,
            actor_id=_current_user_id(),
            step_type=req.step_type,
            content=req.content,
        )
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return step.__dict__


@router.post("/attempts/{attempt_id}/submit")
def submit_attempt(attempt_id: str, svc: AttemptService = Depends(get_attempt_service)):
    try:
        attempt = svc.submit(attempt_id, actor_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return attempt.__dict__


@router.post("/attempts/{attempt_id}/review")
def review_attempt(
    attempt_id: str, req: ReviewAttemptRequest, svc: AttemptService = Depends(get_attempt_service)
):
    try:
        attempt = svc.record_review(
            attempt_id,
            reviewer_id=_current_user_id(),
            notes=req.notes,
            step_marks=req.step_marks,
        )
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return attempt.__dict__


# ---------------------------------------------------------------------------
# Virtual patient sessions (plan WP6)
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    attempt_id: str = Field(..., min_length=1)


class PatientActionRequest(BaseModel):
    action_type: str = Field(..., pattern="^(begin|ask_question|order_exam|advance_phase|submit_disposition)$")
    text: str = Field(default="", max_length=2000)
    exam_name: str = Field(default="", max_length=200)
    option: str = Field(default="", max_length=200)


def get_patient_service(conn: Any = Depends(get_conn)):
    from deeptutor.clinical.virtual_patient.service import PatientSessionService

    return PatientSessionService(conn)


@router.post("/patient-sessions")
def create_patient_session(
    req: CreateSessionRequest, svc=Depends(get_patient_service)
):
    try:
        session = svc.create_session(req.attempt_id, actor_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return session


@router.get("/patient-sessions/{session_id}")
def get_patient_session(session_id: str, svc=Depends(get_patient_service)):
    try:
        session = svc.get_session(session_id, actor_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return session


@router.post("/patient-sessions/{session_id}/actions")
def perform_patient_action(
    session_id: str, req: PatientActionRequest, svc=Depends(get_patient_service)
):
    from deeptutor.clinical.virtual_patient.engine import Action

    action = Action(
        action_type=req.action_type,
        payload={"text": req.text, "exam_name": req.exam_name, "option": req.option},
    )
    try:
        result = svc.perform_action(session_id, actor_id=_current_user_id(), action=action)
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return result


@router.get("/patient-sessions/{session_id}/events")
def list_patient_events(session_id: str, svc=Depends(get_patient_service)):
    try:
        events = svc.list_events(session_id, actor_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return events


# ---------------------------------------------------------------------------
# Assessment framework (plan WP7): rules_v1 first pass + teacher review
# ---------------------------------------------------------------------------


def get_assessment_service(conn: Any = Depends(get_conn)):
    from deeptutor.assessment.service import AssessmentService

    return AssessmentService(conn)


class AssessmentReviewRequest(BaseModel):
    action: str = Field(..., pattern="^(agree|override|dismiss)$")
    final_error_type: str | None = Field(
        default=None,
        pattern="^(symptom_attribution|differential_exclusion|evidence_integration|decision_rationale|logic_breakpoint|evidence_gap|decision_bias|ethical_blind_spot)$",
    )
    final_is_correct: bool | None = None
    comment: str = Field(default="", max_length=4000)


@router.post("/attempts/{attempt_id}/assess")
def run_assessment(
    attempt_id: str, svc=Depends(get_assessment_service)
):
    try:
        run = svc.run_assessment(attempt_id, actor_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return run


@router.get("/assessment-runs/{run_id}")
def get_assessment_run(run_id: str, svc=Depends(get_assessment_service)):
    try:
        run = svc.get_run(run_id, actor_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return run


@router.get("/teacher/assessment-queue")
def assessment_queue(class_id: str, svc=Depends(get_assessment_service)):
    try:
        items = svc.review_queue(class_id, actor_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return items


@router.post("/assessment-scores/{score_id}/review")
def review_assessment_score(
    score_id: str, req: AssessmentReviewRequest, svc=Depends(get_assessment_service)
):
    try:
        review = svc.record_review(
            score_id,
            teacher_id=_current_user_id(),
            action=req.action,
            final_error_type=req.final_error_type,
            final_is_correct=req.final_is_correct,
            comment=req.comment,
        )
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return review


# ---------------------------------------------------------------------------
# Teacher analytics (plan WP8, minimal)
# ---------------------------------------------------------------------------


def get_analytics_service(conn: Any = Depends(get_conn)):
    from deeptutor.analytics.service import AnalyticsService

    return AnalyticsService(conn)


class InterventionRequest(BaseModel):
    class_id: str = Field(..., min_length=1)
    student_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1, max_length=2000)
    note: str = Field(default="", max_length=4000)


class InterventionResolveRequest(BaseModel):
    outcome: str = Field(default="", max_length=4000)


@router.get("/teacher/classes/{class_id}/dashboard")
def teacher_dashboard(class_id: str, svc=Depends(get_analytics_service)):
    try:
        return svc.class_overview(class_id, actor_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc


@router.get("/teacher/classes/{class_id}/risk-flags")
def teacher_risk_flags(class_id: str, svc=Depends(get_analytics_service)):
    try:
        return svc.risk_flags(class_id, actor_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc


@router.post("/teacher/interventions")
def record_intervention(req: InterventionRequest, svc=Depends(get_analytics_service)):
    try:
        intervention = svc.record_intervention(
            req.class_id,
            teacher_id=_current_user_id(),
            student_id=req.student_id,
            reason=req.reason,
            note=req.note,
        )
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return intervention


@router.get("/teacher/classes/{class_id}/interventions")
def list_interventions(class_id: str, svc=Depends(get_analytics_service)):
    try:
        return svc.list_interventions(class_id, actor_id=_current_user_id())
    except TeachingError as exc:
        raise _to_http(exc) from exc


@router.post("/teacher/interventions/{intervention_id}/resolve")
def resolve_intervention(
    intervention_id: str, req: InterventionResolveRequest, svc=Depends(get_analytics_service)
):
    try:
        intervention = svc.resolve_intervention(
            intervention_id, actor_id=_current_user_id(), outcome=req.outcome
        )
    except TeachingError as exc:
        raise _to_http(exc) from exc
    return intervention
