"""Typed records returned by the teaching and clinical services."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

COURSE_ROLES = ("course_admin", "teacher", "reviewer", "student")
CASE_LEVELS = ("L1", "L2", "L3", "L4")
DIMENSIONS = ("complexity", "diagnostic", "decision", "situational")

# The eight reasoning-error categories of the official error dictionary
# (D2 decision pending formal sign-off; these codes are the working set from
# the 2026-07-24 plan §5.3 and must not be renamed casually).
ERROR_TYPES = (
    "symptom_attribution",
    "differential_exclusion",
    "evidence_integration",
    "decision_rationale",
    "logic_breakpoint",
    "evidence_gap",
    "decision_bias",
    "ethical_blind_spot",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Tenant:
    tenant_id: str
    name: str
    status: str = "active"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass
class Course:
    course_id: str
    tenant_id: str
    code: str
    title: str
    description: str = ""
    status: str = "active"
    created_by: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass
class TeachingClass:
    class_id: str
    course_id: str
    name: str
    semester: str = ""
    status: str = "active"
    created_by: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass
class ClassMembership:
    membership_id: str
    class_id: str
    user_id: str
    role: str
    enrolled_at: str = field(default_factory=utc_now)
    dropped_at: str | None = None


@dataclass
class Assignment:
    assignment_id: str
    class_id: str
    case_id: str
    title: str
    description: str = ""
    due_at: str | None = None
    status: str = "draft"
    created_by: str = ""
    created_at: str = field(default_factory=utc_now)


@dataclass
class ClinicalCase:
    case_id: str
    tenant_id: str
    case_code: str
    title: str
    level: str
    disease: str = ""
    dimension_complexity: int = 1
    dimension_diagnostic: int = 1
    dimension_decision: int = 1
    dimension_situational: int = 1
    status: str = "draft"
    current_version_id: str | None = None
    created_by: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass
class CaseVersion:
    version_id: str
    case_id: str
    version: int
    content: dict
    content_hash: str
    status: str = "draft"
    change_note: str = ""
    created_by: str = ""
    created_at: str = field(default_factory=utc_now)


@dataclass
class CaseReview:
    review_id: str
    case_id: str
    version_id: str
    reviewer_id: str
    decision: str
    comments: str = ""
    created_at: str = field(default_factory=utc_now)


@dataclass
class CaseAttempt:
    attempt_id: str
    assignment_id: str
    student_id: str
    status: str = "in_progress"
    started_at: str = field(default_factory=utc_now)
    submitted_at: str | None = None
    reviewed_at: str | None = None
    reviewer_id: str | None = None
    review_notes: str = ""
    created_at: str = field(default_factory=utc_now)


@dataclass
class ReasoningStep:
    step_id: str
    attempt_id: str
    step_type: str
    content: str
    is_correct: int | None = None
    ai_confidence: float | None = None
    reviewed_by_teacher: int = 0
    teacher_override: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
