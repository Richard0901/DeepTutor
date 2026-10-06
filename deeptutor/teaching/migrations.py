"""Schema migrations for the central teaching database.

Each entry owns one forward ``up`` and one matching ``down`` script.  The
teaching organization tables (0001) and the clinical case content tables
(0002) mirror the data domains in the 2026-07-24 secondary development plan
§4.3: 教学组织 and 病例内容.  Learning-process, assessment and governance
domains get their own later revisions once their work packages start.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    up: str
    down: str


_MIGRATION_0001_UP = """
CREATE TABLE tenants (
    tenant_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE courses (
    course_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants (tenant_id),
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('draft', 'active', 'archived')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (tenant_id, code)
);

CREATE TABLE course_versions (
    version_id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses (course_id),
    version INTEGER NOT NULL,
    changelog TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (course_id, version)
);

CREATE TABLE teaching_classes (
    class_id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses (course_id),
    name TEXT NOT NULL,
    semester TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE class_memberships (
    membership_id TEXT PRIMARY KEY,
    class_id TEXT NOT NULL REFERENCES teaching_classes (class_id),
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('course_admin', 'teacher', 'reviewer', 'student')),
    enrolled_at TEXT NOT NULL,
    dropped_at TEXT,
    UNIQUE (class_id, user_id)
);

CREATE INDEX idx_class_memberships_user ON class_memberships (user_id);
CREATE INDEX idx_teaching_classes_course ON teaching_classes (course_id);
"""

_MIGRATION_0001_DOWN = """
DROP INDEX IF EXISTS idx_teaching_classes_course;
DROP INDEX IF EXISTS idx_class_memberships_user;
DROP TABLE IF EXISTS class_memberships;
DROP TABLE IF EXISTS teaching_classes;
DROP TABLE IF EXISTS course_versions;
DROP TABLE IF EXISTS courses;
DROP TABLE IF EXISTS tenants;
"""

_MIGRATION_0002_UP = """
CREATE TABLE clinical_cases (
    case_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants (tenant_id),
    case_code TEXT NOT NULL,
    title TEXT NOT NULL,
    disease TEXT NOT NULL DEFAULT '',
    level TEXT NOT NULL CHECK (level IN ('L1', 'L2', 'L3', 'L4')),
    dimension_complexity INTEGER NOT NULL CHECK (dimension_complexity BETWEEN 1 AND 5),
    dimension_diagnostic INTEGER NOT NULL CHECK (dimension_diagnostic BETWEEN 1 AND 5),
    dimension_decision INTEGER NOT NULL CHECK (dimension_decision BETWEEN 1 AND 5),
    dimension_situational INTEGER NOT NULL CHECK (dimension_situational BETWEEN 1 AND 5),
    -- case-level workflow state; per-version review state lives in case_versions
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'under_review', 'approved', 'published', 'retired')),
    current_version_id TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (tenant_id, case_code)
);

-- Case versions are immutable once approved or published; edits always go
-- through a new draft version (plan hard constraint #5, 事件溯源).
CREATE TABLE case_versions (
    version_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES clinical_cases (case_id),
    version INTEGER NOT NULL,
    content_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'under_review', 'approved', 'rejected', 'published', 'superseded')),
    change_note TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (case_id, version)
);

CREATE TABLE case_dimensions (
    id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES case_versions (version_id),
    dimension TEXT NOT NULL
        CHECK (dimension IN ('complexity', 'diagnostic', 'decision', 'situational')),
    score INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
    rationale TEXT NOT NULL DEFAULT '',
    UNIQUE (version_id, dimension)
);

CREATE TABLE case_knowledge_points (
    id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES case_versions (version_id),
    kp_code TEXT NOT NULL,
    kp_name TEXT NOT NULL,
    UNIQUE (version_id, kp_code)
);

CREATE TABLE case_review_records (
    review_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES clinical_cases (case_id),
    version_id TEXT NOT NULL REFERENCES case_versions (version_id),
    reviewer_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approve', 'reject', 'request_changes')),
    comments TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX idx_case_review_version ON case_review_records (version_id);

CREATE INDEX idx_clinical_cases_tenant ON clinical_cases (tenant_id, status);

CREATE TABLE assignments (
    assignment_id TEXT PRIMARY KEY,
    class_id TEXT NOT NULL REFERENCES teaching_classes (class_id),
    case_id TEXT NOT NULL REFERENCES clinical_cases (case_id),
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    due_at TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'open', 'closed')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_assignments_class ON assignments (class_id, status);
"""

_MIGRATION_0002_DOWN = """
DROP INDEX IF EXISTS idx_assignments_class;
DROP TABLE IF EXISTS assignments;
DROP INDEX IF EXISTS idx_clinical_cases_tenant;
DROP INDEX IF EXISTS idx_case_review_version;
DROP TABLE IF EXISTS case_review_records;
DROP TABLE IF EXISTS case_knowledge_points;
DROP TABLE IF EXISTS case_dimensions;
DROP TABLE IF EXISTS case_versions;
DROP TABLE IF EXISTS clinical_cases;
"""

_MIGRATION_0003_UP = """
CREATE TABLE case_attempts (
    attempt_id TEXT PRIMARY KEY,
    assignment_id TEXT NOT NULL REFERENCES assignments (assignment_id),
    student_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'in_progress'
        CHECK (status IN ('in_progress', 'submitted', 'reviewed')),
    started_at TEXT NOT NULL,
    submitted_at TEXT,
    reviewed_at TEXT,
    reviewer_id TEXT,
    review_notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX idx_case_attempts_assignment ON case_attempts (assignment_id, student_id);
CREATE INDEX idx_case_attempts_student ON case_attempts (student_id);

-- Reasoning steps are append-only: submitted attempts are locked and no
-- row is ever rewritten (plan hard constraint #5, 事件溯源/可回放).
CREATE TABLE reasoning_steps (
    step_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL REFERENCES case_attempts (attempt_id),
    step_type TEXT NOT NULL CHECK (step_type IN (
        'problem_presentation', 'differential_diagnosis', 'key_evidence',
        'investigation', 'disposition', 'reassessment')),
    content TEXT NOT NULL,
    is_correct INTEGER CHECK (is_correct IN (0, 1)),
    ai_confidence REAL,
    reviewed_by_teacher INTEGER NOT NULL DEFAULT 0 CHECK (reviewed_by_teacher IN (0, 1)),
    teacher_override TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_reasoning_steps_attempt ON reasoning_steps (attempt_id);
"""

_MIGRATION_0003_DOWN = """
DROP INDEX IF EXISTS idx_reasoning_steps_attempt;
DROP TABLE IF EXISTS reasoning_steps;
DROP INDEX IF EXISTS idx_case_attempts_student;
DROP INDEX IF EXISTS idx_case_attempts_assignment;
DROP TABLE IF EXISTS case_attempts;
"""

MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, name="teaching_organization", up=_MIGRATION_0001_UP, down=_MIGRATION_0001_DOWN),
    Migration(version=2, name="clinical_case_content", up=_MIGRATION_0002_UP, down=_MIGRATION_0002_DOWN),
    Migration(version=3, name="clinical_attempts", up=_MIGRATION_0003_UP, down=_MIGRATION_0003_DOWN),
)
